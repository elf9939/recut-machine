"""Word-by-word captions + hook (ASS subtitles), same style as the clip pages."""
import re

BLEEP = re.compile(r"\b(n+i+g+(a+|e+r+|g+a+|g+e+r+|gaz?|guh)s?|f+u+c+k\w*|b+i+t+c+h\w*|s+h+i+t+\w*|p+u+s+s+y|d+i+c+k\w*|c+u+n+t|f+a+g+\w*|r+e+t+a+r+d\w*|w+h+o+r+e\w*)\b", re.I)


def clean(t):
    """Star out slurs/heavy swearing in captions (TikTok/YouTube limit reach on them): fuck -> f**k."""
    t = re.sub(r'(?i)(mother)f+u+c+k', lambda m: m.group(1) + 'f**k', t)
    return BLEEP.sub(lambda m: m.group(0)[0] + '*' * (len(m.group(0)) - 2) + m.group(0)[-1], t)



def t(x): return f'{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}'


def ass_file(words, start, end, hook, path, cap_y=905):
    head = ('[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n[V4+ Styles]\n'
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n'
            'Style: Cap,Arial Black,78,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,1,7,2,5,90,140,0\n'
            'Style: Hook,Arial Black,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,4,1,8,70,70,255\n\n'
            '[Events]\nFormat: Layer, Start, End, Style, MarginL, MarginR, MarginV, Text\n')
    hook = ''.join(ch for ch in hook if ord(ch) < 0x2000).strip()   # the caption font can't draw emoji
    ev = [f'Dialogue: 1,{t(0)},{t(end - start)},Hook,0,0,0,{hook}']
    ws = [w for w in words if w['e'] > start and w['s'] < end]
    chunks, cur = [], []
    for w in ws:
        cur.append(w)
        if len(cur) == 3 or w['w'][-1:] in '.!?,': chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    cur = 0.0                                     # end of the last caption shown; nothing may start before it
    for ci, c in enumerate(chunks):
        nxt = (chunks[ci + 1][0]['s'] - start) if ci + 1 < len(chunks) else end - start
        s1 = min(c[-1]['e'] - start + 0.15, end - start, max(nxt, c[-1]['e'] - start))
        for k, w in enumerate(c):                 # current word highlighted yellow
            ws0 = max(w['s'] - start, cur, 0)
            ws1 = (c[k + 1]['s'] - start) if k + 1 < len(c) else s1
            ws1 = min(max(ws1, ws0 + 0.05), end - start)
            if ws1 <= ws0: continue
            cur = ws1
            txt = ' '.join(('{\\c&H00FFFF&}' + clean(x['w']).upper() + '{\\c&HFFFFFF&}') if j == k else clean(x['w']).upper()
                           for j, x in enumerate(c))
            ev.append(f'Dialogue: 0,{t(ws0)},{t(ws1)},Cap,0,0,0,{{\\pos(540,{cap_y})}}{txt}')
    open(path, 'w').write(head + '\n'.join(ev) + '\n')


