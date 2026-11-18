# Tiny Gemini (free tier) client. Key lives in ~/.gemini_key (saved by ~/Projects/clipper/auto/add-gemini-key.sh).
import json, os, urllib.request
MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-flash-latest']

def ask_json(prompt):
    key = os.environ.get('GEMINI_API_KEY') or open(os.path.expanduser('~/.gemini_key')).read().strip()
    body = json.dumps({'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                       'generationConfig': {'temperature': 0.5, 'responseMimeType': 'application/json', 'maxOutputTokens': 8192}}).encode()
    last = None
    for m in MODELS:
        req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent', data=body,
                                     headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=180))
            text = ''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts'])
            return json.loads(text)
        except Exception as e:
            last = e
    raise RuntimeError(f'Gemini failed: {last}')


def ask_json_video(path, prompt):
    """Gemini watches a (small) video file and answers in JSON. Used by the clip quality inspector."""
    import base64
    key = os.environ.get('GEMINI_API_KEY') or open(os.path.expanduser('~/.gemini_key')).read().strip()
    data = base64.b64encode(open(path, 'rb').read()).decode()
    body = json.dumps({'contents': [{'role': 'user', 'parts': [{'inline_data': {'mime_type': 'video/mp4', 'data': data}}, {'text': prompt}]}],
                       'generationConfig': {'temperature': 0.3, 'responseMimeType': 'application/json', 'maxOutputTokens': 4096}}).encode()
    last = None
    for m in MODELS:
        req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent', data=body,
                                     headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=240))
            return json.loads(''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts']))
        except Exception as e:
            last = e
    raise RuntimeError(f'Gemini video failed: {last}')
