#!/usr/bin/env python3
"""Recut Media daily batch (runs in the cloud, no Mac needed):
find English Kick streamers with a business email -> AI judges their top clips -> 3 vertical captioned clips
-> upload -> cheat sheet + drafted email -> card in the PostBotz Outreach tab (Dakota reviews and sends from his phone).

  python3 recut/run.py --want 15

Public repo: this file and its logs never print anyone's email address. Nothing is ever sent from here.
"""
import argparse, json, os, re, secrets, subprocess, sys, time, urllib.request

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
    return json.load(urllib.request.urlopen(urllib.request.Request('https://kick.com' + path, headers={'User-Agent': UA}), timeout=30))


def whisper(path):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=4)
    segs, _ = _model.transcribe(path, word_timestamps=True, vad_filter=True, language='en')
    return [{'w': w.word.strip(), 's': round(w.start, 2), 'e': round(w.end, 2)} for s in segs for w in (s.words or [])]


# ---------------- 1. find creators ----------------
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
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',
                    '-movflags', '+faststart', out], check=True)
    os.remove(ass)


def make_clips(p, work, n=3):
    clips = []
    for span in ('week', 'month'):
        try: d = kick(f'/api/v2/channels/{p["slug"]}/clips?sort=view&time={span}')
        except Exception: continue
        clips += [{'url': c['clip_url'], 'title': c.get('title', '')} for c in d.get('clips', []) if (c.get('duration') or 0) <= 90 and c['clip_url'] not in [x['url'] for x in clips]]
        if len(clips) >= 20: break
    pool = []
    for i, c in enumerate(clips[:20], 1):
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
    return d['subject'], d['body']


def cheat_sheet(p):
    try:
        facts = {'platform': 'Kick', 'followers': p['followers'], 'category': p['category'], 'bio': p['bio'], 'socials': p['socials']}
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
    os.makedirs(os.path.dirname(SEEN), exist_ok=True); open(SEEN, 'w').write('\n'.join(sorted(seen)))
    done, t_start = 0, time.time()
    for p in found:
        if done >= a.want or time.time() - t_start > 4.5 * 3600: break    # stay inside GitHub's 6-hour job limit
        print(f'\n{p["name"]} ({p["followers"]:,} followers)', flush=True)
        work = os.path.join(WORK, p['slug']); os.makedirs(work, exist_ok=True)
        try:
            made = make_clips(p, work)
            if not made: print('  no good clips — skipped'); continue
            urls = [upload(m['file'], f'recut_{p["slug"]}_{k + 1}.mp4') for k, m in enumerate(made)]
            pid = f'{p["slug"]}-{secrets.token_hex(4)}'; link = f'https://recut-previews.vercel.app/c/{pid}'
            subj, body = email_for(p['name'], [m['moment'] for m in made])
            hub('/api/agents?outreach', {'action': 'add', 'item': {'id': p['slug'], 'pid': pid, 'name': p['name'], 'platform': 'Kick', 'followers': p['followers'],
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
