# beat_gh_reg.py — BeatAPI (new-api) авторег через GitHub OAuth. Без капчи (turnstile_enabled=False).
# Usage: python beat_gh_reg.py N [start_idx]
import os
import sys, os, json, time, random, re, urllib.request, urllib.error, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import gh_http

API = 'https://api.beatapi.io/api'
CLIENT_ID = 'Ov23liL5qt3yDfI1xJi8'
REDIRECT_URI = 'https://beatapi.io/oauth/github'
AFF = '7WEA'
BANK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'accounts.jsonl')
USED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'used_gh.txt')
POOL = 'C:/Users/User/tmp/gh_accounts.json'

HDRS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0',
        'Accept': 'application/json', 'Origin': 'https://beatapi.io', 'Referer': 'https://beatapi.io/'}


def api(path, method='GET', data=None, token=None, sid=None, uid=None):
    h = dict(HDRS)
    if token:
        h['Authorization'] = 'Bea' + 'rer ' + token
    if sid:
        h['x-auth-session'] = sid
    if uid:
        h['New-Api-User'] = str(uid)
    body = json.dumps(data).encode() if data is not None else None
    if body:
        h['Content-Type'] = 'application/json'
    r = urllib.request.Request(API + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {'raw': raw[:300]}


def load_used():
    if os.path.exists(USED):
        return set(l.strip() for l in open(USED) if l.strip())
    return set()


def mark_used(login):
    with open(USED, 'a') as f:
        f.write(login + '\n')


def save(rec):
    with open(BANK, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def register_one(acc, idx):
    login = acc['login']
    out = {'idx': idx, 'gh_login': login, 'gh_email': acc.get('email'), 'ts': int(time.time())}
    # 1. flow token
    st, r = api('/oauth/state', 'POST', {'provider': 'github', 'intent': 'login', 'aff': AFF})
    flow = None
    if isinstance(r, str):
        flow = r
    elif isinstance(r, dict):
        dd = r.get('data')
        if isinstance(dd, dict):
            flow = dd.get('flow_token')
        elif isinstance(dd, str):
            flow = dd
        flow = flow or r.get('flow_token')
    if not flow:
        out['err'] = f'state {st}: {str(r)[:150]}'
        return out
    out['flow_token'] = flow[:16]
    # 2. GH login
    print('  step: gh login', flush=True)
    s = gh_http.GHSession(bind=False)
    try:
        ok = s.login(login, acc['password'], acc.get('totp'))
    except Exception as e:
        out['err'] = f'gh_login exc: {e}'
        return out
    if not ok:
        out['err'] = f'gh_login fail: {"; ".join(s.detail[-3:])[:200]}'
        return out
    # 3. authorize (custom: with redirect_uri)
    print('  step: authorize', flush=True)
    url = (f'https://github.com/login/oauth/authorize?client_id={CLIENT_ID}'
           f'&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe="")}'
           f'&response_type=code&scope={urllib.parse.quote("read:user user:email")}'
           f'&state={urllib.parse.quote(flow)}')
    code, err = None, None
    stt, hh, body = s.get(url)
    loc = hh.get('Location', '')
    if stt in (301, 302):
        code = s._code_from(loc)
        if not code:
            err = f'redir no code: {loc[:120]}'
    elif stt == 200:
        # meta-refresh page ("OAuth application authorized") — code+state inside body
        m = re.search(r'oauth/github\?code=([a-f0-9]{16,})[^"\']*state=([A-Za-z0-9_\-]+)', body)
        if m:
            code, flow = m.group(1), m.group(2)
        else:
            m = re.search(r'code=([a-f0-9]{16,})', body)
            if m:
                code = m.group(1)
        if not code:
            tok = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', body)
            if tok:
                fields = {'authorize': '1', 'authenticity_token': tok.group(1),
                          'client_id': CLIENT_ID, 'state': flow, 'scope': 'read:user user:email'}
                st2, h2, b2 = s.post_form(url, fields)
                loc2 = h2.get('Location', '')
                code = s._code_from(loc2) if st2 in (301, 302) else None
                if not code:
                    m2 = re.search(r'oauth/github\?code=([a-f0-9]{16,})[^"\']*state=([A-Za-z0-9_\-]+)', b2)
                    if m2:
                        code, flow = m2.group(1), m2.group(2)
                if not code:
                    err = f'consent no code http={st2} loc={loc2[:100]}'
            else:
                err = f'no code/token (len={len(body)}) title={re.search(r"<title>([^<]*)", body).group(1) if re.search(r"<title>([^<]*)", body) else "?"}'
    else:
        err = f'authorize http={stt}'
    if not code:
        out['err'] = err or 'no code'
        return out
    out['code'] = code[:10]
    # 4. exchange
    print('  step: exchange', flush=True)
    st, r = api(f'/oauth/github?code={urllib.parse.quote(code)}&state={urllib.parse.quote(flow)}')
    if st != 200 or (isinstance(r, dict) and r.get('success') is False):
        out['err'] = f'exchange {st}: {str(r)[:400]}'
        return out
    d = r.get('data', r) if isinstance(r, dict) else r
    tok = d.get('access_token') or d.get('token')
    if not tok:
        out['err'] = f'no access_token: {str(r)[:200]}'
        return out
    out['access_token'] = tok
    out['beat_user'] = d.get('username') or d.get('loginIdentifier')
    out['user_id'] = d.get('user_id') or d.get('id')
    sid = d.get('session_id') or (d.get('session') or {}).get('sid') or ''
    # 5. self (quota)
    st, r = api('/user/self', token=tok, sid=sid)
    uid = None
    if st == 200 and isinstance(r, dict):
        dd = r.get('data', r)
        out['quota'] = dd.get('quota')
        out['beat_username'] = dd.get('username')
        out['beat_id'] = dd.get('id')
        uid = dd.get('id')
    # 6. create API key (trailing slash! 307 otherwise)
    st, r = api('/token/', 'POST', {'name': f'farm{int(time.time())%100000}', 'remain_quota': 500000,
                                    'expired_time': -1, 'unlimited_quota': True,
                                    'model_limits_enabled': False, 'model_limits': ''}, token=tok, sid=sid, uid=uid)
    tid = None
    if st == 200 and isinstance(r, dict) and r.get('success'):
        d = r.get('data') or {}
        tid = d.get('id') if isinstance(d, dict) else d
    out['token_create'] = f'{st}:{str(r)[:120]}'
    if tid:
        # full key: POST /token/{id}/key with New-Api-User header (GET = 404)
        st, r = api(f'/token/{tid}/key', 'POST', token=tok, sid=sid, uid=uid)
        if st == 200 and isinstance(r, dict):
            d = r.get('data') or {}
            key = d.get('key') if isinstance(d, dict) else d
            if key and '*' not in str(key):
                out['api_key'] = key
                out['token_id'] = tid
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    accs = json.load(open(POOL, encoding='utf-8'))
    # gmail-domain accounts first (whitelisted + verified on GH)
    accs = sorted(accs, key=lambda a: 0 if str(a.get('email', '')).endswith('@gmail.com') else 1)
    used = load_used()
    done = 0
    i = start
    while done < n and i < len(accs):
        acc = accs[i]
        i += 1
        if acc['login'] in used:
            continue
        print(f'--- [{i-1}] {acc["login"]}', flush=True)
        try:
            rec = register_one(acc, i - 1)
        except Exception as e:
            rec = {'idx': i - 1, 'gh_login': acc['login'], 'err': f'exc: {e}'}
        mark_used(acc['login'])
        ok = bool(rec.get('access_token'))
        print('OK' if rec.get('api_key') else ('PARTIAL' if ok else 'FAIL'), json.dumps({k: str(v)[:60] for k, v in rec.items() if k != 'access_token'}, ensure_ascii=False), flush=True)
        if ok:
            save(rec)
            if rec.get('api_key'):
                done += 1
        elif '429' in str(rec.get('err', '')) or 'limit' in str(rec.get('err', '')).lower():
            print('RATE LIMIT — sleeping 600s', flush=True)
            time.sleep(600)
        time.sleep(random.uniform(75, 110))
    print(f'DONE {done}/{n}, next idx {i}')


if __name__ == '__main__':
    main()
