#!/usr/bin/env python3
"""Recut Media daily batch (runs in the cloud, no Mac needed):
find English Kick streamers with a business email -> AI judges their top clips -> 3 vertical captioned clips
-> upload -> cheat sheet + drafted email -> card in the PostBotz Outreach tab (Dakota reviews and sends from his phone).

  python3 recut/run.py --want 15

Public repo: this file and its logs never print anyone's email address. Nothing is ever sent from here.
"""
import urllib.error, argparse, json, os, re, secrets, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from captions import ass_file
from gemini import ask_json

HUB = 'https://post-hub-nine.vercel.app'
KEY = os.environ.get('PH_AUTOMATION_KEY') or open(os.path.expanduser('~/.posthub_key')).read().strip()
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
BIN = os.path.expanduser('~/.local/bin')
YTDLP = [os.path.join(BIN, 'yt-dlp') if os.path.exists(os.path.join(BIN, 'yt-dlp')) else 'yt-dlp', '--no-warnings']
FFMPEG = os.path.join(BIN, 'ffmpeg') if os.path.exists(os.path.join(BIN, 'ffmpeg')) else 'ffmpeg'
SEEN = os.path.join(ROOT, 'data', 'seen.txt')          # creator handles already looked at (public info only)
WORK = os.path.join(ROOT, 'work')
BRAND, FROM, PRICE = 'Recut Media', 'recutmedia@proton.me', '$600/mo'
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
_model = None


def hub(path, body=None):
    req = urllib.request.Request(HUB + path, data=json.dumps(body).encode() if body else None,
                                 headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=240))


def kick(path):
    """Kick API with backoff: Kick rate-limits cloud IPs (429) — wait and retry instead of losing every creator (Nov 19: 0 emails)."""
    for k in range(6):
        try:
            time.sleep(1.5)                       # gentle pace between calls
            return json.load(urllib.request.urlopen(urllib.request.Request('https://kick.com' + path, headers={'User-Agent': UA}), timeout=30))
        except urllib.error.HTTPError as e:
            if e.code != 429 or k == 5: raise
            w = int(e.headers.get('Retry-After') or 0) or 15 * (k + 1); print(f'  Kick busy (429) — waiting {w}s', flush=True); time.sleep(min(w, 90))


def whisper(path):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=4)
    segs, _ = _model.transcribe(path, word_timestamps=True, vad_filter=True, language='en')
    return [{'w': w.word.strip(), 's': round(w.start, 2), 'e': round(w.end, 2)} for s in segs for w in (s.words or [])]


# ---------------- 1. find creators ----------------
def twitch():
    """Official Twitch API (owner's own app keys: env TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET)."""
    import urllib.parse
    cid, sec = os.environ.get('TWITCH_CLIENT_ID'), os.environ.get('TWITCH_CLIENT_SECRET')
    if not (cid and sec):
        f = os.path.expanduser('~/.twitch_keys')
        if not os.path.exists(f): return None
        cid, sec = (open(f).read().split() + ['', ''])[:2]
    tok = json.load(urllib.request.urlopen(urllib.request.Request('https://id.twitch.tv/oauth2/token', data=urllib.parse.urlencode({'client_id': cid, 'client_secret': sec, 'grant_type': 'client_credentials'}).encode()), timeout=30))['access_token']
    H = {'Client-Id': cid, 'Authorization': 'Bearer ' + tok}
    return lambda path: json.load(urllib.request.urlopen(urllib.request.Request('https://api.twitch.tv/helix/' + path, headers=H), timeout=30))


SKIP = re.compile(r'clip|highlight|moments|best ?of|compilation|fan ?page|reupload|re-upload|daily |casino|slots|gambl|betting|poker|onlyfans|18\+|nsfw|bikini|politic', re.I)


def find_twitch(want, seen, already):
    """Live English Twitch streamers with a real audience (25-3000 viewers) and a business email in their bio."""
    get = twitch(); out = []
    if not get: print('  (no Twitch keys — Kick only)', flush=True); return out
    cur = None
    for _ in range(25):
        if len(out) >= want: break
        d = get('streams?language=en&first=100' + (f'&after={cur}' if cur else '')); cur = (d.get('pagination') or {}).get('cursor')
        live = [x for x in d['data'] if 25 <= x['viewer_count'] <= 3000 and ('tw:' + x['user_login']) not in seen and x['user_login'] not in already
                and not SKIP.search(x.get('game_name', '') + ' ' + x.get('title', ''))]
        for i in range(0, len(live), 100):
            ids = '&'.join('id=' + x['user_id'] for x in live[i:i + 100])
            if not ids: continue
            users = {u['id']: u for u in get('users?' + ids)['data']}
            for x in live[i:i + 100]:
                seen.add('tw:' + x['user_login']); u = users.get(x['user_id']) or {}
                bio = u.get('description') or ''
                if SKIP.search(x['user_login'] + ' ' + bio): continue
                mails = [m for m in EMAIL.findall(bio) if 'example.' not in m.lower()]
                if not mails: continue
                out.append({'slug': x['user_login'], 'name': x['user_name'], 'followers': 0, 'viewers': x['viewer_count'], 'email': mails[0].rstrip('.'),
                            'category': x.get('game_name', ''), 'bio': bio[:600], 'socials': {}, 'platform': 'Twitch', 'tid': x['user_id']})
                print(f'  ✓ {x["user_name"]} — Twitch, {x["viewer_count"]} live viewers, {x.get("game_name", "")}', flush=True)
                if len(out) >= want: break
        if not cur: break
    return out


def find(want, seen, already):
    out = []
    for page in range(1, 40):
        if len(out) >= want: break
        try: d = kick(f'/stream/livestreams/en?page={page}&limit=24&sort=desc')
        except Exception as e: print('  kick list failed', e); break
        for s in d.get('data', []):
            if len(out) >= want: break
            ch = (s.get('channel') or {}).get('slug'); v = s.get('viewer_count') or 0
            if (s.get('language') or '').lower() not in ('english', 'en') or v > 1500: continue
            if v < 150: return out
            if not ch or ch in seen or ch in already: continue
            cat = ((s.get('categories') or [{}])[0].get('name') or '')
            if re.search(r'slots|casino|gambl|poker|bikini|hot tub|pools|politic', cat, re.I): continue
            seen.add(ch)
            try: c = kick(f'/api/v2/channels/{ch}')
            except Exception: continue
            u = c.get('user') or {}; mails = [m for m in EMAIL.findall(u.get('bio') or '') if 'example.' not in m.lower()]
            who = ' '.join([ch, u.get('username') or '', u.get('bio') or '']).lower()
            if re.search(r'clip|highlight|moments|best ?of|compilation|fan ?page|reupload|re-upload|daily ', who): continue   # clip/fan accounts aren't clients
            followers = int(c.get('followers_count') or c.get('followersCount') or 0)
            if not mails or followers < 10_000: continue
            out.append({'slug': ch, 'name': u.get('username') or ch, 'followers': followers, 'email': mails[0].rstrip('.'), 'category': cat,
                        'bio': (u.get('bio') or '')[:600], 'socials': {k: u.get(k) for k in ('twitter', 'instagram', 'youtube', 'tiktok') if u.get(k)}})
            print(f'  ✓ {out[-1]["name"]} — {followers:,} followers, {cat}', flush=True)
            time.sleep(1)
    return out


# ---------------- 2. clips ----------------
def render(src, words, hook, out):
    """Whole frame kept (nobody cropped out): hook on top, video in the middle, captions under it, blurred fill."""
    t0 = max(0.0, (words[0]['s'] - 0.35) if words else 0.0)
    end = max([w['e'] for w in words] + [t0 + 1]) + 0.6
    ass = out + '.ass'; ass_file(words, t0, end, hook, ass, 1330)
    vf = ('[0:v]fps=30,split[m][b];[m]crop=iw*0.8:ih,scale=1080:-2,setsar=1[v];'
          '[b]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,scale=1080:1920,eq=brightness=-0.22:saturation=1.2,setsar=1,fps=30[bg];'
          f"[bg][v]overlay=0:470:shortest=1,ass='{ass}'")
    subprocess.run(['nice', '-n', '10', FFMPEG, '-y', '-loglevel', 'error', '-ss', f'{t0:.2f}', '-i', src, '-t', f'{end - t0:.2f}', '-filter_complex', vf, '-r', '30',
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',   # 44.1 kHz: loudnorm outputs 96 kHz, which iPhones won't play
                    '-movflags', '+faststart', out], check=True)
    os.remove(ass)


def make_clips(p, work, n=3):
    clips = []
    if p.get('platform') == 'Twitch':
        import datetime
        get = twitch(); since = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        for c in get(f'clips?broadcaster_id={p["tid"]}&first=12&started_at={since}')['data']:
            if c.get('duration', 0) <= 90: clips.append({'url': c['url'], 'title': c.get('title', '')})
    for span in (('week', 'month') if p.get('platform') != 'Twitch' else ()):
        try: d = kick(f'/api/v2/channels/{p["slug"]}/clips?sort=view&time={span}')
        except Exception: continue
        clips += [{'url': c['clip_url'], 'title': c.get('title', '')} for c in d.get('clips', []) if (c.get('duration') or 0) <= 90 and c['clip_url'] not in [x['url'] for x in clips]]
        if len(clips) >= 12: break
    pool = []
    for i, c in enumerate(clips[:12], 1):   # 12 not 20: cost (top-viewed clips win anyway)
        src = os.path.join(work, f'src{i}.mp4')
        try:
            r = subprocess.run(YTDLP + ['-q', '-f', 'best[height<=1080]/best', '-o', src, '--hls-prefer-native', '--add-header', f'User-Agent:{UA}', c['url']], timeout=240)
            if r.returncode or not os.path.exists(src): continue
        except subprocess.TimeoutExpired: continue
        words = whisper(src)
        if len(words) < 15: continue
        pool.append({'i': len(pool), 'src': src, 'words': words, 'title': c['title'], 'text': ' '.join(w['w'] for w in words)[:1200]})
    if not pool: return []
    ranked = ask_json(f"""You choose sample clips to show the streamer {p['name']}, to win them as a clipping client. From the candidates below, pick the {n} best.
A clip is good ONLY if a stranger scrolling TikTok would stop for it: genuinely funny, hype, shocking, or a short story with a clear payoff.
NEVER pick: gambling / slots / casino / betting moments, clips that are mostly music or song lyrics, routine gameplay callouts, or anything where nothing happens.
Fewer than {n} is fine if the rest are weak.
Return JSON [{{"i": candidate number, "hook": "3-8 word on-screen hook, true to what is said, no hashtags", "moment": "6-12 word description of the moment"}}], best first.
Candidates:
""" + '\n'.join(f"#{x['i']} title: {x['title']!r} | transcript: {x['text']}" for x in pool))
    made = []
    for r in ranked[:n]:
        x = next((y for y in pool if y['i'] == r.get('i')), None)
        if not x: continue
        f = os.path.join(work, f'clip{len(made) + 1}.mp4'); render(x['src'], x['words'], r['hook'], f)
        made.append({'file': f, 'hook': r['hook'], 'moment': r['moment']}); print(f'    clip {len(made)}: {r["hook"]}', flush=True)
    return made


def upload(f, name):
    u = hub('/api/upload', {'files': [{'fileName': name, 'mimeType': 'video/mp4'}]})['urls'][0]
    code = subprocess.run(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '--retry', '3', '-X', 'PUT', '-H', 'Content-Type: video/mp4', '--data-binary', '@' + f, u['uploadUrl']],
                          capture_output=True, text=True).stdout
    if not code.startswith('2'): raise RuntimeError(f'upload failed {code}')
    return u['publicUrl']


# ---------------- 3. email + cheat sheet ----------------
def email_for(name, moments):
    d = ask_json(f'''Write a short cold email from Dakota at {BRAND} to the streamer "{name}". Return JSON {{"subject": "...", "body": "..."}}.
Facts you may use (do not invent anything else, no fake compliments, never claim to be a long-time fan):
- We cut {len(moments)} ready-to-post vertical clip(s) from their recent streams. The moments: {json.dumps(moments)}.
- The clips are at {{LINK}} (keep that placeholder exactly). They can post them free either way.
- Offer: we post 2 clips a day to their TikTok and YouTube Shorts with captions and titles done, they never touch it. {PRICE}, cancel anytime.
Rules: under 110 words, casual and specific, name the first moment in the first line (describe it kindly, never insult the streamer or anyone in it),
one question at the end ("Want me to keep them coming?" or similar), no call booking, no emojis, no hype words. Subject: 3-7 words, about their content.
End the body with exactly:
Dakota
{BRAND} · {FROM}

P.S. Not interested? Just reply "no" and I won't reach out again.''')
    return (d.get('subject') or '').strip() or '3 clips from your recent streams', d['body']   # never a blank subject


def cheat_sheet(p):
    try:
        facts = {'platform': p.get('platform', 'Kick'), 'followers': p['followers'] or None, 'live_viewers': p.get('viewers'), 'category': p['category'], 'bio': p['bio'], 'socials': p['socials']}
        r = ask_json(f"""Write a short pre-call cheat sheet about the streamer "{p['name']}" for Dakota, who runs a clipping agency.
Use ONLY these public facts; if something isn't in them, leave it out: {json.dumps(facts)}
Return JSON {{"who": "2 sentences", "size": "one line", "talking_points": ["3 specific things to mention or ask"], "clip_angle": "one sentence"}}""")
        return (f"Who: {r['who']}\n\nSize: {r['size']}\n\nTalking points:\n" + ''.join(f'- {x}\n' for x in r['talking_points']) +
                f"\nClip angle: {r['clip_angle']}\n\nFrom their public channel info. Double-check before you say it.")
    except Exception: return ''


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--want', type=int, default=15); a = ap.parse_args()
    seen = set(open(SEEN).read().split()) if os.path.exists(SEEN) else set()
    already = {i['id'] for i in hub('/api/agents?outreach').get('items', [])}
    print('Finding creators…', flush=True)
    found = find(a.want + 5, seen, already)            # a few spare: some won't have good clips
    if len(found) < a.want * 2:                          # Kick's live pool is small: top up from Twitch (most creators don't have 2+ great clips)
        found += find_twitch(a.want * 2 - len(found), seen, already | {f['slug'] for f in found})
    print(f'{len(found)} creators to try', flush=True)
    os.makedirs(os.path.dirname(SEEN), exist_ok=True); open(SEEN, 'w').write('\n'.join(sorted(seen)))
    done, t_start = 0, time.time()
    for p in found:
        if done >= a.want or time.time() - t_start > 4.5 * 3600: break    # stay inside GitHub's 6-hour job limit
        print(f'\n{p["name"]} ({p.get("platform", "Kick")}, ' + (f'{p["followers"]:,} followers)' if p['followers'] else f'{p.get("viewers")} live viewers)'), flush=True)
        work = os.path.join(WORK, p['slug']); os.makedirs(work, exist_ok=True)
        try:
            made = make_clips(p, work)
            if len(made) < 2: print(f'  only {len(made)} good clip(s) — skipped (every email needs at least 2)'); continue
            urls = [upload(m['file'], f'recut_{p["slug"]}_{k + 1}.mp4') for k, m in enumerate(made)]
            pid = f'{p["slug"]}-{secrets.token_hex(4)}'; link = f'https://recut-previews.vercel.app/c/{pid}'
            subj, body = email_for(p['name'], [m['moment'] for m in made])
            hub('/api/agents?outreach', {'action': 'add', 'item': {'id': p['slug'], 'pid': pid, 'name': p['name'], 'platform': p.get('platform', 'Kick'), 'followers': p['followers'],
                 'contact': p['email'], 'page': link, 'clips': urls, 'hooks': [m['hook'] for m in made], 'subject': subj,
                 'body': body.replace('{LINK}', link), 'cheat': cheat_sheet(p)}})
            done += 1; print('  → added to the Outreach tab', flush=True)
        except Exception as e:
            print('  failed:', str(e)[:120], flush=True)
        finally:
            subprocess.run(['rm', '-rf', work])
    print(f'\n{done} creators ready in the Outreach tab')
    try: hub('/api/push', {'action': 'send', 'title': 'Recut Media 📨', 'body': f'{done} new creators ready to send in your Outreach tab', 'url': '/#outreach'})
    except Exception: pass


if __name__ == '__main__':
    main()
