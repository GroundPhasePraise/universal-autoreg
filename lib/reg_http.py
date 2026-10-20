"""reg_http v2 — HTTP-only GitHub-OAuth регистрация на New API панелях.
Оба контракта state: POST flow_token (rc.2x) и GET state-строка (классика).
Cookie-режим после callback (New-Api-User). Полный ключ, инкрементальный out.
python reg_http.py <panel> <start_idx> <count>
"""
import os
import sys, json, time, urllib.parse, re
import newapi_lib as L
import gh_http

PANELS = {
    # новые (POST state, flow_token)
    'flushapi': 'https://flushapi.fun',
    'kktoken': 'https://kktoken.cc',
    'justwoker': 'https://api.justwoker.icu',
    'relaybases': 'https://relaybases.com',
    'kiosapi': 'https://kiosapi.com',
    'ainx': 'https://api.ainx.cc',
    'aitoke': 'https://aitoke.top',
    'chuan': 'https://chuan.sylu.cc',
    'motomoto': 'https://motomoto.lol',
    'creiting': 'https://myapi.creitingameplays.com',
    'augmentproxy': 'https://api.augmentproxy.top',
    # классические (GET state)
    'gogotoken': 'https://gogotoken.org',
    'aiyiwei': 'https://aiyiwei.vip',
    'makerend': 'https://makerend.com',
    'vveai': 'https://api.vveai.com',
    'gptge': 'https://api.gpt.ge',
    'ultrarouter': 'https://ultrarouter.org',
    'straitapi': 'https://straitapi.com',
    'tokeness': 'https://tokeness.io',
}
PNAME = sys.argv[1] if len(sys.argv) > 1 else 'gogotoken'
START = int(sys.argv[2]) if len(sys.argv) > 2 else 1
COUNT = int(sys.argv[3]) if len(sys.argv) > 3 else 2
IDXLIST = [int(x) for x in sys.argv[4].split(',')] if len(sys.argv) > 4 else None

_ACC_PATH = os.environ.get('UA_GH_ACCOUNTS') or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'gh_accounts.json')
ACC = json.load(open(_ACC_PATH, encoding='utf-8')) if os.path.exists(_ACC_PATH) else []
OUT = 'github_oauth_panels'

INTENTS = {'motomoto': 'register'}
CID_CACHE = {'flushapi': 'Ov23li3WpJvZg1RmcPcl', 'chuan': 'Ov23liXNX4lOlgRUPFi8',
             'kktoken': 'Ov23lig0AsT86oSKP21N', 'justwoker': 'Ov23liBGecTYSePKpXQC',
             'relaybases': 'Ov23liYO9Ul4qW2rypBj', 'gogotoken': 'Ov23liQNIDPxXZ172Gqw',
             'vveai': 'Ov23li6rCJ2tqnOgQDlB', 'gptge': 'Ov23li6rCJ2tqnOgQDlB',
             'kiosapi': 'Ov23lic5Fki7aTBDXvuU', 'ainx': 'Ov23liuuQXP0xCv4skmv',
             'aitoke': 'Ov23li6SBA5XnOJ9S5rF', 'chuan2': '', 'motomoto': 'Ov23liboOooSL0Spc5Qv',
             'creiting': 'Ov23liavxEXkGkvn3SU1', 'augmentproxy': 'Ov23liWKQNdzPCQadM7A',
             'aiyiwei': 'Ov23liGR0nkftfZrSbMs', 'makerend': 'Ov23li6SE47nqtkjBGEq'}
SMOKE_MODEL = {'relaybases': 'gpt-6-sol', 'chuan': 'gemini-3.1-flash', 'flushapi': 'glm-5.3-flash'}




def panel_state(p, intent='login'):
    """POST flow_token (новый) → GET state (классика)."""
    st, b = p.req('/api/oauth/state', {'provider': 'github', 'intent': intent})
    j = p.j(b)
    if st == 200 and j.get('success') is not False:
        d = j.get('data')
        if isinstance(d, dict) and (d.get('flow_token') or d.get('state')):
            return (d.get('flow_token') or d.get('state')), 'post'
        if isinstance(d, str) and d:
            return d, 'post'
    st, b = p.req('/api/oauth/state')
    j = p.j(b)
    if st == 200 and j.get('success') is not False:
        d = j.get('data')
        if isinstance(d, str) and d:
            return d, 'get'
        if isinstance(d, dict) and (d.get('state') or d.get('flow_token')):
            return (d.get('state') or d.get('flow_token')), 'get'
    return None, f'state fail: POST {st} {str(j.get("message", b))[:120]}'


def panel_callback(p, code, st8):
    """GET /api/oauth/github?code&state → (atok, uid, err).
    err=None = успех; atok=None → cookie-режим; uid — из data.id (классика)."""
    path = f'/api/oauth/github?code={urllib.parse.quote(code)}&state={urllib.parse.quote(st8)}'
    st, b = p.req(path)
    j = p.j(b)
    if st != 200 or j.get('success') is False:
        return None, None, f'callback http={st} {str(j.get("message", b))[:220]}'
    if not j and b.lstrip()[:1] == '<':
        # HTML-страница ошибки (мотомото-стайл): вытаскиваем текст
        m = re.search(r'<p[^>]*>([^<]{4,200})</p>', b)
        return None, None, f'callback html: {(m.group(1) if m else b[:160])}'
    d = j.get('data')
    if isinstance(d, str) and d:
        return d, None, None
    d = d if isinstance(d, dict) else {}
    atok = d.get('access_token') or (d.get('session') or {}).get('access_token')
    return atok, d.get('id'), None


def preq(p, path, atok=None, uid=None, hdr='New-Api-User', body=None, method=None):
    """Запрос через opener панели с выбором юзер-хедера (New-Api-User / X-Api-User)."""
    h = {'User-Agent': L.UA, 'Accept': 'application/json'}
    if atok:
        h['Authorization'] = L.AUTH + atok
    elif uid:
        h[hdr] = str(uid)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    r = urllib.request.Request(p.base + path, data=data, headers=h,
                                method=method or ('POST' if body is not None else 'GET'))
    try:
        with p.op.open(r, timeout=30) as resp:
            return resp.status, resp.read().decode('utf-8', 'ignore')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'ignore')
    except Exception as e:
        return -1, f'{type(e).__name__}: {str(e)[:110]}'


def harvest_key(p, atok, uid=None):
    """self → token → полный ключ. Три режима: token / cookie New-Api-User /
    cookie X-Api-User (VOAPI). Возвращает rec."""
    rec = {'auth_mode': 'token' if atok else 'cookie'}
    hdr = 'New-Api-User'
    if atok:
        st, me = p.me(atok)
    elif uid:
        p.cookie_uid = uid
        st, me = p.me(None)  # lib сам шлёт New-Api-User
        if not me.get('id'):
            st, b = preq(p, '/api/user/self', uid=uid, hdr='X-Api-User')
            me = p.j(b).get('data') or {}
            if me.get('id'):
                hdr = 'X-Api-User'
    else:
        st, me = p.me(None)
    rec.update({'self_http': st, 'user_id': me.get('id') or uid,
                'role': me.get('role'), 'quota': me.get('quota'),
                'aff_code': me.get('aff_code'), 'mail': me.get('email'),
                'panel_username': me.get('username'), 'user_hdr': hdr})
    if not (me.get('id') or uid):
        return rec

    def tok_req(path, body=None, method=None):
        return preq(p, path, atok=atok, uid=None if atok else uid, hdr=hdr,
                    body=body, method=method)

    base_body = {'name': 'eni', 'key': '', 'expired_time': -1, 'remain_quota': 500000000,
                 'unlimited_quota': True, 'model_limits_enabled': False,
                 'model_limits': ''}
    NULLV = L.NULLV
    j3, st3, b3 = {}, -1, ''
    for grp in (NULLV, 'auto', 'default', 'claude-lite'):
        body3 = dict(base_body, **({'group': grp} if grp else {}))
        st3, b3 = tok_req('/api/token/', body3)
        j3 = p.j(b3)
        if j3.get('data') or j3.get('success') is True:
            break
        msg3 = str(j3.get('message', ''))
        if 'group' not in msg3.lower():
            break  # не групповая ошибка — дальше не перебираем
    rec['token_create'] = f'{st3} {b3[:110]}'
    created = j3.get('data') if isinstance(j3.get('data'), dict) else {}
    created_key = created.get('key')  # VOAPI: полный ключ сразу в ответе создания
    st4, b4 = tok_req('/api/token/?p=0&size=100')
    d4 = p.j(b4).get('data')
    items = d4 if isinstance(d4, list) else (d4 or {}).get('items', [])
    if not items:
        rec['tokens_raw'] = f'{st4} {b4[:120]}'
    else:
        tid = items[0].get('id')
        rec['token_id'] = tid
        rec['masked_key'] = items[0].get('key')
        st5, b5 = tok_req(f'/api/token/{tid}/key', {}, method='POST')
        rec['api_key'] = (p.j(b5).get('data') or {}).get('key')
        rec['key_http'] = st5
        if not rec.get('api_key'):
            rec['key_raw'] = b5[:150]
    if not rec.get('api_key') and created_key:
        rec['api_key'] = created_key
        rec['key_source'] = 'create-response'
        rec['token_id'] = rec.get('token_id') or created.get('id')
    if rec.get('api_key'):
        smoke_key(p, rec)
        # FIX: token without usable group → models_count=0. Try updating group via PUT.
        if rec.get('models_count', 0) == 0 and rec.get('token_id'):
            for g in ('free', 'gpt', 'claud', 'grok', 'auto', 'default', '国产模型'):
                body_g = {'id': rec['token_id'], 'name': 'eni', 'key': '',
                          'expired_time': -1, 'remain_quota': 500000000,
                          'unlimited_quota': True, 'model_limits_enabled': False,
                          'model_limits': '', 'group': g}
                stg, bg = tok_req('/api/token/', body_g, method='PUT')
                if stg == 200 and p.j(bg).get('success'):
                    smoke_key(p, rec)
                    rec['group_fixed'] = g
                    if rec.get('models_count', 0) > 0:
                        break
    return rec


def smoke_key(p, rec):
    """/v1/models + /v1/chat/completions — ключ должен отвечать."""
    try:
        h = {'User-Agent': L.UA, 'Authorization': L.AUTH + rec['api_key']}
        r = urllib.request.Request(p.base + '/v1/models', headers=h)
        try:
            with p.op.open(r, timeout=25) as resp:
                st, b = resp.status, resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            st, b = e.code, e.read().decode('utf-8', 'ignore')
        rec['models_http'] = st
        j = p.j(b)
        ids = [m.get('id') for m in (j.get('data') or []) if isinstance(m, dict)]
        rec['models_count'] = len(ids)
        cheap = [m for m in ids if any(s in m.lower() for s in ('flash', 'mini', 'lite', 'nano'))]
        pref = SMOKE_MODEL.get(PNAME)
        if pref and pref in ids:
            model = pref
        elif cheap:
            model = cheap[0]
        else:
            model = ids[0] if ids else 'gpt-4o-mini'
        body = json.dumps({'model': model, 'max_tokens': 8,
                           'messages': [{'role': 'user', 'content': 'ping'}]}).encode()
        h2 = dict(h, **{'Content-Type': 'application/json'})
        r2 = urllib.request.Request(p.base + '/v1/chat/completions', data=body, headers=h2)
        try:
            with p.op.open(r2, timeout=100) as resp:
                st2, b2 = resp.status, resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            st2, b2 = e.code, e.read().decode('utf-8', 'ignore')
        rec['chat_http'] = st2
        rec['chat_model'] = model
        if st2 == 200:
            ch = (p.j(b2).get('choices') or [{}])[0]
            msg = ch.get('message') or {}
            rec['chat_ok'] = bool(msg)
            if msg:
                rec['live_model'] = model
                rec['smoke_reply'] = str(msg.get('content') or msg.get('reasoning_content') or '')[:60]
            else:
                rec['chat_err'] = b2[:140]
        else:
            rec['chat_err'] = b2[:140]
    except Exception as e:
        rec['smoke_exc'] = f'{type(e).__name__}: {str(e)[:100]}'



def main():
    base = PANELS[PNAME]
    ok_cnt = fail_cnt = 0
    for i in (IDXLIST if IDXLIST else range(START, min(START + COUNT, len(ACC)))):
        a = ACC[i]
        print(f'\n===== [{i}] {a["login"]} → {PNAME} =====', flush=True)
        rec = {'slice': 'github_oauth', 'panel': PNAME, 'base': base,
               'gh_login': a['login'], 'gh_mail': a['email'], 'ts': time.strftime('%H:%M:%S')}
        try:
            p = L.Panel(PNAME, base)
            stt, sd = p.status()
            cid = sd.get('github_client_id') or CID_CACHE.get(PNAME)
            rec['version'] = sd.get('version')
            rec['status_http'] = stt
            if not cid:
                rec['error'] = f'no github_client_id (status http={stt})'
                print('  !', rec['error'], flush=True)
                L.merge_into(OUT, [rec], keys=('panel', 'gh_login'))
                fail_cnt += 1
                continue
            st8, mode_or_err = panel_state(p, INTENTS.get(PNAME, 'login'))
            if not st8:
                rec['error'] = mode_or_err
                print('  ! state:', mode_or_err, flush=True)
                L.merge_into(OUT, [rec], keys=('panel', 'gh_login'))
                fail_cnt += 1
                continue
            rec['state_mode'] = mode_or_err
            print(f'  state ok ({mode_or_err}): {str(st8)[:36]}...', flush=True)

            gh = gh_http.GHSession(bind=True)
            ok, msg = gh.login(a['login'], a['password'], a.get('totp'))
            rec['gh_login_ok'] = ok
            if not ok:
                rec['error'] = f'gh login: {msg} | {"; ".join(gh.detail)}'
                print('  ! gh login:', msg, gh.detail, flush=True)
                L.merge_into(OUT, [rec], keys=('panel', 'gh_login'))
                fail_cnt += 1
                time.sleep(3)
                continue
            code, cerr = gh.oauth_code(cid, st8)
            if not code:
                rec['error'] = f'oauth code: {cerr} | {"; ".join(gh.detail)}'
                print('  ! code:', cerr, flush=True)
                L.merge_into(OUT, [rec], keys=('panel', 'gh_login'))
                fail_cnt += 1
                time.sleep(3)
                continue
            rec['gh_code'] = code[:12] + '...'
            print(f'  code ok: {code[:16]}...', flush=True)

            atok, uid, cerr = panel_callback(p, code, st8)
            if cerr is not None:
                rec['callback'] = cerr
                print('  ! callback:', cerr, flush=True)
                L.merge_into(OUT, [rec], keys=('panel', 'gh_login'))
                fail_cnt += 1
                time.sleep(3)
                continue
            rec['callback'] = 'ok(token)' if atok else 'ok(cookie)'
            if uid and not atok:
                p.cookie_uid = uid
            if atok:
                rec['access_token'] = atok if len(str(atok)) < 400 else str(atok)[:200]
            rec.update(harvest_key(p, atok, uid=uid))

            print(f"  user_id={rec.get('user_id')} quota={rec.get('quota')} "
                  f"mode={rec.get('auth_mode')} key={'YES' if rec.get('api_key') else 'NO'}",
                  flush=True)
            ok_cnt += 1
        except Exception as e:
            rec['error'] = f'exc: {type(e).__name__}: {str(e)[:160]}'
            print('  !!', rec['error'], flush=True)
            fail_cnt += 1
        L.merge_into(OUT, [rec], keys=('panel', 'gh_login'))
        time.sleep(2)
    print(f'\nИТОГ {PNAME}: ok={ok_cnt} fail={fail_cnt}', flush=True)


if __name__ == '__main__':
    main()
