# -*- coding: utf-8 -*-
"""GitHub OAuth signup on treg.to — grant probe via OAuth door (promo_eligible default True)."""
import os
import sys, os, re, json, time, random, string, urllib.request, urllib.error, urllib.parse, http.cookiejar
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import gh_http

B = 'https://treg.to'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
BEARER = 'Bea' + 'rer '
POOL = os.environ.get('GH_POOL', 'C:/Users/User/tmp/hoplite-gateway/data/gh_accounts.json')
STATE_F = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get('GH_STATE', 'gh_grant_state.json'))
BANK_F = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'treg_gh_accounts.jsonl')


def load_state():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {'idx': 0, 'used': []}


def save_state(st):
    with open(STATE_F, 'w') as f:
        json.dump(st, f)


class Jar(http.cookiejar.CookieJar):
    pass


def opener():
    jar = Jar()
    op = urllib.request.build_opener(urllib.request.HTTPSHandler(),
                                     urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [('User-Agent', UA), ('Accept', '*/*'),
                     ('Accept-Language', 'en-US,en;q=0.9')]
    return op, jar


def req(op, url, data=None, method=None, timeout=40, ctype=None, extra=None):
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header('User-Agent', UA)
    r.add_header('Accept', '*/*')
    if ctype:
        r.add_header('Content-Type', ctype)
    if extra:
        for k, v in extra.items():
            r.add_header(k, v)
    try:
        with op.open(r, timeout=timeout) as resp:
            return resp.status, resp.read()[:400000]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:4000]
    except Exception as e:
        return -1, ('%s: %s' % (type(e).__name__, str(e)[:120])).encode()


def rndname(pfx):
    return pfx + ''.join(random.choices(string.ascii_lowercase + string.digits, k=7))


def gh_authorize(sess, full_url):
    """Follow treg's authorize URL (with redirect_uri) inside GH session; return code."""
    st, h, body = sess.get(full_url)
    sess.detail.append('authorize http=%s loc=%s' % (st, h.get('Location', '')[:90]))
    loc = h.get('Location', '')
    if st in (301, 302):
        code = gh_http.GHSession._code_from(loc)
        if code:
            return code, None
        return None, 'redirect without code: ' + loc[:140]
    if st != 200:
        return None, 'authorize http=%s %s' % (st, body[:150])
    m = re.search(r'url=[^"?&]+\?code=([a-f0-9]+)', body)
    if m:
        return m.group(1), None
    m = re.search(r'[?&]code=([a-f0-9]{16,})', body)
    if m:
        return m.group(1), None
    tok = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', body)
    if not tok:
        tok = re.search(r'value="([^"]+)"[^>]*name="authenticity_token"', body)
    if not tok:
        return None, 'consent without token len=%d: %s' % (len(body), body[:200])
    fields = {'authorize': '1', 'authenticity_token': tok.group(1)}
    st2, h2, body2 = sess.post_form(full_url, fields)
    loc2 = h2.get('Location', '')
    sess.detail.append('consent http=%s loc=%s' % (st2, loc2[:90]))
    if st2 in (301, 302):
        code = gh_http.GHSession._code_from(loc2)
        if code:
            return code, None
        return None, 'consent redirect without code: ' + loc2[:140]
    m = re.search(r'url=[^"?&]+\?code=([a-f0-9]+)', body2)
    if m:
        return m.group(1), None
    m = re.search(r'[?&]code=([a-f0-9]{16,})', body2)
    if m:
        return m.group(1), None
    return None, 'consent http=%s len=%d: %s' % (st2, len(body2), body2[:200])


def run_one(gh_acc):
    op, jar = opener()
    # 1. treg oauth start
    st, body = req(op, B + '/auth/github', timeout=30)
    if st != 302:
        return None, 'start http=%s %s' % (st, body[:150])
    loc = None
    for c in jar:
        if c.name.lower() == 'location':
            loc = c.value
    # urllib strips Location into headers, cookies only hold state; re-request with manual redirect
    return None, 'placeholder'


def run(gh_acc):
    op = urllib.request.build_opener()
    # step 1: get authorize URL + state cookie (manual, no auto-redirect)
    class NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, rq, fp, code, msg, headers, newurl):
            return None
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(NoRedir, urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [('User-Agent', UA)]
    try:
        with op.open(B + '/auth/github', timeout=30) as resp:
            return None, 'unexpected 200 on /auth/github'
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307):
            return None, 'start http=%s' % e.code
        loc = e.headers.get('Location', '')
    m = re.search(r'client_id=([^&]+)', loc)
    ms = re.search(r'state=([^&]+)', loc)
    if not m or not ms:
        return None, 'no client_id/state in %s' % loc[:120]
    client_id, state = m.group(1), ms.group(1)
    state_cookie = ''
    for c in jar:
        if c.name == 'treg_oauth_state':
            state_cookie = c.value
    print('client_id=%s state=%s cookie=%s' % (client_id[:12], state[:12], bool(state_cookie)), flush=True)

    # step 2: GH login + authorize with FULL url (redirect_uri matters)
    sess = gh_http.GHSession(bind=False)
    ok, err = sess.login(gh_acc['login'], gh_acc['password'], gh_acc.get('totp', ''))
    if not ok:
        return None, 'gh login failed: ' + str(err)[:120]
    code, err = gh_authorize(sess, loc)
    if not code:
        return None, 'gh authorize failed: ' + str(err)[:200]
    print('gh code ok', flush=True)

    # step 3: treg callback with state cookie
    cb = B + '/auth/github/callback?code=%s&state=%s' % (urllib.parse.quote(code), urllib.parse.quote(state))
    st, body = req(op, cb, timeout=40, extra={'Cookie': 'treg_oauth_state=' + state_cookie})
    print('callback http=%s len=%d' % (st, len(body)), flush=True)
    if st not in (200, 302, 303, 307):
        return None, 'callback http=%s %s' % (st, body[:300])
    sess_cookie = ''
    for c in jar:
        if 'session' in c.name or 'treg' in c.name:
            sess_cookie += '%s=%s; ' % (c.name, c.value)
    print('cookies: %s' % ', '.join(sorted(set(c.name for c in jar))), flush=True)
    if not sess_cookie.strip():
        return None, 'no session cookie after callback; body=%s' % body[:300].decode('utf-8', 'ignore')

    # step 4: orgs
    st, body = req(op, B + '/orgs', timeout=30, extra={'Cookie': sess_cookie})
    print('GET /orgs http=%s %s' % (st, body[:200]), flush=True)
    name = rndname('studio')
    payload = json.dumps({'name': name}).encode()
    st, body = req(op, B + '/orgs', data=payload, method='POST', timeout=30,
                   ctype='application/json', extra={'Cookie': sess_cookie})
    print('POST /orgs http=%s %s' % (st, body[:250]), flush=True)
    org_id = slug = None
    try:
        pj = json.loads(body)
        org_id = pj.get('org_id')
        slug = pj.get('org') or pj.get('slug')
    except Exception:
        pass
    if not org_id:
        st, body = req(op, B + '/orgs', timeout=30, extra={'Cookie': sess_cookie})
        try:
            orgs = json.loads(body)
        except Exception:
            orgs = []
        if isinstance(orgs, dict):
            orgs = orgs.get('orgs') or orgs.get('data') or []
        if orgs:
            org_id = orgs[0].get('org_id') or orgs[0].get('id')
            slug = orgs[0].get('org') or orgs[0].get('slug')
    print('org_id=%s slug=%s' % (org_id, slug), flush=True)

    # step 5: cli token
    st, body = req(op, B + '/auth/cli-token', timeout=30,
                   extra={'Cookie': sess_cookie, 'X-Treg-Org': str(slug or org_id or '')})
    print('cli-token http=%s' % st, flush=True)
    try:
        tok = json.loads(body).get('token', '')
    except Exception:
        tok = ''
    if not tok:
        return {'email': gh_acc.get('email'), 'gh_login': gh_acc['login'],
                'org': slug, 'org_id': org_id, 'cookie': sess_cookie.strip()}, 'no cli token: %s' % body[:200]

    # step 6: balance
    bal = -1.0
    if org_id:
        st2, b2 = req(op, '%s/orgs/%s/balance?limit=3' % (B, org_id), timeout=30,
                      extra={'X-Treg-Token': tok, 'X-Treg-Key-Protocol': '1'})
        try:
            d2 = json.loads(b2)
            bal = d2.get('balance_micro', d2.get('balance', -1)) / 1e6
        except Exception:
            pass
    rec = {'ts': time.time(), 'email': gh_acc.get('email'), 'gh_login': gh_acc['login'],
           'org': slug, 'org_id': org_id, 'token': tok, 'balance_usd': bal, 'via': 'github-oauth'}
    with open(BANK_F, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec, 'bal=$%.2f' % bal


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    pool = json.load(open(POOL))
    st = load_state()
    done = 0
    for i in range(n):
        idx = st['idx']
        if idx >= len(pool):
            print('pool exhausted'); break
        acc = pool[idx]
        st['idx'] = idx + 1
        save_state(st)
        print('=== acc %d/%d gh=%s' % (i + 1, n, acc['login']), flush=True)
        rec, msg = run(acc)
        print('RESULT: %s | %s' % (msg, json.dumps(rec, ensure_ascii=False)[:300] if rec else '-'), flush=True)
        if rec and rec.get('balance_usd', 0) > 0:
            done += 1
        time.sleep(random.uniform(8, 15))
    print('GRANT>0: %d/%d' % (done, n))


if __name__ == '__main__':
    main()
