#!/usr/bin/env python3
"""gh_device_auth — device-flow авторизация gh CLI через уже залогиненную GHSession.

1. gh auth login --web печатает one-time code XXXX-XXXX и поллит github.com/login/oauth/access_token
2. Мы: GHSession.login(account) -> GET /login/device -> POST user_code -> authorize-confirm
3. gh получает gho_-токен (scopes: repo,read:org,gist) и пишет в свой keyring/hosts.yml
4. gh auth token -> токен; сохраняем в .gh_push_tokens.json

Usage: python gh_device_auth.py
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from gh_session import GHSession, find_form, form_fields

POOL = 'C:/Users/User/tmp/gh_accounts.json'
BANK = 'C:/Users/User/tmp/beat_autoreg/accounts.jsonl'
OUT = 'C:/Users/User/tmp/beat_autoreg/.gh_push_tokens.json'
GH = 'https://github.com'


def pick_account():
    pool = {a['login']: a for a in json.load(open(POOL, encoding='utf-8'))}
    recs = [json.loads(l) for l in open(BANK, encoding='utf-8') if l.strip()]
    cands = [r['gh_login'] for r in recs if r.get('access_token') and r['gh_login'] in pool]
    cands = list(dict.fromkeys(cands))[::-1]
    for login in cands:
        return pool[login]
    return None


def approve_device(s, code):
    """Device-flow: select_account -> user-code-N посимвольно -> confirmation -> consent."""
    # 1. select_account
    st, h, body = s.get(GH + '/login/device/select_account')
    if st != 200:
        return False, f'select_account http={st}'
    form = find_form(body, 'select_account')
    fields = form_fields(form) if form else {}
    st2, h2, body2 = s.post_form(GH + '/login/device/select_account', fields)
    loc2 = h2.get('Location', '')
    if st2 in (301, 302) and loc2:
        u = loc2 if loc2.startswith('http') else GH + loc2
        st2, h2, body2 = s.get(u)
    # 2. confirmation form: user-code-0..8 посимвольно (включая дефис)
    cform = find_form(body2, '/login/device/confirmation')
    if not cform:
        return False, f'no confirmation form (http={st2}, len={len(body2)})'
    fields = form_fields(cform)
    chars = list(code)  # 'ABCF-A8AA' -> 9 символов
    for i, ch in enumerate(chars):
        fields[f'user-code-{i}'] = ch
    if 'commit' in fields and not fields['commit']:
        fields['commit'] = 'Continue'
    st3, h3, body3 = s.post_form(GH + '/login/device/confirmation', fields)
    loc3 = h3.get('Location', '')
    if st3 in (301, 302) and loc3:
        u = loc3 if loc3.startswith('http') else GH + loc3
        st3, h3, body3 = s.get(u)
    if 'Device activated' in body3 or 'Congratulations' in body3:
        return True, 'activated (no consent)'
    open('C:/Users/User/tmp/beat_autoreg/consent_debug.html', 'w', encoding='utf-8').write(body3)
    # 3. consent страница gh CLI OAuth app: форма с authenticity_token + Authorize
    m = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', body3)
    if not m:
        return False, f'no consent token (http={st3}, len={len(body3)})'
    aform = None
    for mm in re.finditer(r'<form[^>]*>.*?</form>', body3, re.S):
        if 'authenticity_token' in mm.group(0):
            aform = mm.group(0)
            break
    action = GH + '/login/oauth/authorize'
    if aform:
        am = re.search(r'action="([^"]+)"', aform)
        if am:
            action = am.group(1)
            if not action.startswith('http'):
                action = GH + action
        fields = form_fields(aform)
    else:
        fields = {'authenticity_token': m.group(1)}
    fields['authenticity_token'] = m.group(1)
    fields['authorize'] = '1'   # КРИТИЧНО: кнопка Authorize (0 = Deny = access_denied)
    st4, h4, body4 = s.post_form(action, fields)
    loc4 = h4.get('Location', '')
    if st4 in (301, 302) and loc4:
        u = loc4 if loc4.startswith('http') else GH + loc4
        st4, h4, body4 = s.get(u)
    if 'Device activated' in body4 or 'Congratulations' in body4 or st4 == 200:
        return True, f'consent ok http={st4}'
    return False, f'consent unclear http={st4} len={len(body4)}'


def main():
    if len(sys.argv) > 1:
        pool = {a['login']: a for a in json.load(open(POOL, encoding='utf-8'))}
        acc = pool.get(sys.argv[1])
    else:
        acc = pick_account()
    if not acc:
        print('NO_ACCOUNT')
        return
    login = acc['login']
    print('account:', login)
    # 1. GHSession login
    s = GHSession()
    ok, msg = s.login(login, acc['password'], acc.get('totp'))
    print('gh login:', ok, msg)
    if not ok:
        print('LOGIN_FAIL')
        return
    # 2. gh auth login --web в фоне (pty через subprocess + pipes)
    env = dict(os.environ)
    env['GH_PROMPT_DISABLED'] = '1'
    proc = subprocess.Popen(
        ['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', env=env)
    code = None
    buf = ''
    deadline = time.time() + 60
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.2)
            continue
        buf += line
        print('gh:', line.strip(), flush=True)
        m = re.search(r'([A-Z0-9]{4}-[A-Z0-9]{4})', line)
        if m:
            code = m.group(1)
            break
        if proc.poll() is not None:
            break
    if not code:
        print('NO_CODE from gh. buf:', buf[-300:])
        proc.kill()
        return
    print('device code:', code)
    # Enter в gh (откроет "браузер" — упадёт молча, поллинг продолжится)
    try:
        proc.stdin.write('\n')
        proc.stdin.flush()
    except Exception:
        pass
    # 3. approve в GHSession
    ok2, info = approve_device(s, code)
    print('approve:', ok2, info)
    if not ok2:
        proc.kill()
        return
    # 4. ждать завершения gh (поллинг access_token)
    try:
        out, _ = proc.communicate(timeout=60)
        print('gh finished:', (out or '')[-300:])
    except subprocess.TimeoutExpired:
        proc.kill()
        print('gh timeout after approve')
    # 5. gh auth token
    r = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=30)
    tok = r.stdout.strip()
    if tok.startswith(('gho_', 'ghu_', 'ghp_')):
        json.dump([[tok, login]], open(OUT, 'w'))
        print('TOKEN_OK len', len(tok), '-> ', OUT)
    else:
        print('TOKEN_FAIL:', r.stderr[:200])


if __name__ == '__main__':
    main()
