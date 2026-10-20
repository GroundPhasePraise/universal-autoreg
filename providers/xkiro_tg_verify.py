# -*- coding: utf-8 -*-
"""xkiro_farm.py — FULL E2E: GH OAuth -> login -> TG ticket -> bot verify (30M tokens) -> API key -> bank.
One cffi session per account (middleware rotates __xt_rt single-use — cookies MUST stay in-session).
Usage: PYTHONPATH="" Python311 xkiro_farm.py <count> [start]
Bank: C:/Users/User/tmp/xkiro/xkiro_bank.jsonl
"""
import os
import sys, os, json, time, re, asyncio, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
sys.path.insert(0, 'C:/Users/User/tmp/regfarm/github_oauth')
from curl_cffi import requests as cq
import gh_http

XK = 'https://xkiro.com'
API = 'https://api.xkiro.com'
CID = 'Ov23li0EyjNfkXUSKZel'
BANK = r'C:/Users/User/tmp/xkiro/xkiro_bank.jsonl'
GOOD_TG = r'C:/Users/User/tmp/xkiro/xkiro_good_tg.json'  # proven REUSABLE sessions (verified 2+ accounts)
POOL = r'C:/Users/User/tmp/gh_accounts.json'
USED = r'C:/Users/User/tmp/xkiro/xkiro_used_tg.json'
AVAIL = r'C:/Users/User/tmp/mia_avail_sessions.json'
DIRS = [r'C:/Users/User/Desktop/CLEAN_ALIVE_SESSIONS', r'C:/Users/User/.orca/sessions']
IMP = 'chrome131'
H = {'Accept': 'application/json', 'Content-Type': 'application/json',
     'Referer': XK + '/dashboard', 'Origin': XK}

# TG creds
import glob as _g
TG_ID, TG_HASH = None, None
for p in [r'C:/Users/User/tmp/mia_verify_slow.py', r'C:/Users/User/tmp/freemodel/freemodel_full.py']:
    try:
        t = open(p, encoding='utf-8').read()
        m1 = re.search(r'API_ID\s*=\s*(\d+)', t)
        m2 = re.search(r'API_HASH\s*=\s*[\'"]([a-f0-9]+)[\'"]', t)
        if m1 and m2:
            TG_ID, TG_HASH = int(m1.group(1)), m2.group(1)
            break
    except Exception:
        pass

def log(*a):
    print(*a, flush=True)

def good_sessions():
    """Proven reusable TG sessions (rotate, no consumption)."""
    out = []
    try:
        for p in json.load(open(GOOD_TG)):
            if os.path.exists(p):
                out.append(p)
    except Exception:
        pass
    return out

def mark_good(path):
    try:
        g = json.load(open(GOOD_TG))
    except Exception:
        g = []
    if path not in g:
        g.append(path)
        json.dump(g, open(GOOD_TG, 'w'))

def tg_sessions(n=4):
    names = json.load(open(AVAIL))
    try:
        used = set(json.load(open(USED)))
    except Exception:
        used = set()
    # exclude sessions already consumed by miarouter verifier (avoid AuthKeyDuplicated)
    try:
        mstate = json.load(open(r'C:/Users/User/Desktop/farm/miarouter/verifier_state.json'))
        used |= set(mstate.get('used_tg', []))
    except Exception:
        pass
    tail = [b for b in names if b not in used]
    tail = tail[-n:]  # TAIL: miarouter verifier walks head-first
    out = []
    for b in tail:
        for d in DIRS:
            p = os.path.join(d, b)
            if os.path.exists(p):
                out.append(p)
                break
    return out

def mark_tg_used(basename):
    try:
        used = set(json.load(open(USED)))
    except Exception:
        used = set()
    used.add(basename)
    json.dump(sorted(used), open(USED, 'w'))

async def bot_start(sess_path, ticket):
    from telethon import TelegramClient
    name = os.path.basename(sess_path)
    client = TelegramClient(sess_path.replace('.session', ''), TG_ID, TG_HASH)
    try:
        await asyncio.wait_for(client.connect(), 45)
        if not await client.is_user_authorized():
            return name, 'NOT_AUTH'
        await client.send_message('xkiro_official_bot', '/start ' + ticket)
        await asyncio.sleep(9)
        msgs = await client.get_messages('xkiro_official_bot', limit=4)
        txt = ' '.join((m.message or '')[:200] for m in msgs if not m.out).lower()
        if 'verified successfully' in txt or "you've received" in txt:
            return name, 'OK'
        if 'join' in txt or 'channel' in txt:
            from telethon.tl.functions.channels import JoinChannelRequest
            try:
                await client(JoinChannelRequest('xtrouter'))
                await asyncio.sleep(3)
                await client.send_message('xkiro_official_bot', '/start ' + ticket)
                await asyncio.sleep(8)
                msgs = await client.get_messages('xkiro_official_bot', limit=4)
                txt = ' '.join((m.message or '')[:200] for m in msgs if not m.out).lower()
                if 'verified' in txt:
                    return name, 'OK'
                return name, 'REPLY:' + txt[:120]
            except Exception as e:
                return name, 'JOIN_FAIL:' + type(e).__name__
        return name, 'REPLY:' + txt[:120]
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

def farm_one(acc, tgsess):
    lg = acc['login']
    rec = {'gh_login': lg, 'ts': time.strftime('%H:%M:%S')}
    s = cq.Session(impersonate=IMP)
    # 1 state
    try:
        r = s.get(API + '/api/v1/auth/github', headers={**H, 'Accept': 'text/html', 'Sec-Fetch-Site': 'none'},
                  allow_redirects=False, timeout=30)
        loc = r.headers.get('Location', '') or ''
        m = re.search(r'state=([a-f0-9]{16,})', loc)
        if not m:
            m = re.search(r'state=([a-f0-9]{16,})', r.text or '')
        if not m:
            rec['stage'] = 'state'; rec['err'] = f'http={r.status_code}'
            return rec
        state = m.group(1)
    except Exception as e:
        rec['stage'] = 'state'; rec['err'] = str(e)[:100]; return rec
    # 2 gh code
    gh = gh_http.GHSession(bind=False)
    ok, err = gh.login(lg, acc['password'], acc.get('totp'))
    if not ok:
        rec['stage'] = 'gh_login'; rec['err'] = err; return rec
    code, cerr = gh.oauth_code(CID, state, scope='read:user user:email')
    if not code:
        rec['stage'] = 'gh_code'; rec['err'] = cerr; return rec
    # 3 callback (same session!)
    try:
        r3 = s.get(API + f'/api/v1/auth/github/callback?code={code}&state={state}',
                   headers={**H, 'Accept': 'text/html', 'Sec-Fetch-Site': 'cross-site',
                            'Referer': 'https://github.com/'}, timeout=40)
        cks = dict(s.cookies)
        if not cks.get('__xt_at'):
            rec['stage'] = 'callback'; rec['err'] = f'http={r3.status_code} no __xt_at'
            return rec
        rec['cookies'] = cks
    except Exception as e:
        rec['stage'] = 'callback'; rec['err'] = str(e)[:100]; return rec
    # 4 ticket via xkiro.com proxy (cookies same names, set on xkiro.com)
    s2 = cq.Session(impersonate=IMP)
    for k, v in cks.items():
        s2.cookies.set(k, v, domain='xkiro.com')
        s2.cookies.set(k, v, domain='.xkiro.com')
    if not tgsess:
        rec['tg'] = 'NO_TG_SESSION'
    else:
        try:
            rt = s2.post(XK + '/api/v1/me/telegram/ticket', headers=H, data='{}', timeout=25)
            j = rt.json()
            data = j.get('data') or {}
            if data.get('alreadyVerified'):
                rec['tg'] = 'already'
            else:
                dl = data.get('deepLink', '')
                ticket = dl.split('start=')[-1] if 'start=' in dl else ''
                if not ticket:
                    rec['stage'] = 'ticket'; rec['err'] = rt.text[:120]; return rec
                # 5 bot verify
                try:
                    sp, res = asyncio.run(bot_start(tgsess, ticket))
                except Exception as be:
                    res = f'EXC:{type(be).__name__}:{str(be)[:60]}'
                rec['tg'] = res; rec['tg_sess'] = os.path.basename(tgsess)
                if res == 'OK':
                    mark_tg_used(os.path.basename(tgsess))  # consumed: 1 TG acct = 1 xkiro verification
                else:
                    mark_tg_used(os.path.basename(tgsess))  # any failure: never reuse (dup/NOT_AUTH/burned)
        except Exception as e:
            rec['stage'] = 'ticket'; rec['err'] = str(e)[:100]
    # refresh cookies after middleware rotation
    fresh = dict(s2.cookies)
    if fresh.get('__xt_at'):
        rec['cookies'] = {**cks, **fresh}
    # 6 key + wallet + status
    try:
        rk = s2.post(XK + '/api/v1/keys', headers=H, data=json.dumps({'name': 'farm'}), timeout=25)
        jk = rk.json()
        rec['key'] = (jk.get('data') or {}).get('plaintext')
        rec['key_id'] = ((jk.get('data') or {}).get('key') or {}).get('id')
    except Exception as e:
        rec['key_err'] = str(e)[:80]
    try:
        rec['wallet'] = s2.get(XK + '/api/v1/wallet', headers=H, timeout=20).json().get('data')
        rec['tg_status'] = s2.get(XK + '/api/v1/me/telegram/status', headers=H, timeout=20).json().get('data')
    except Exception:
        pass
    rec['stage'] = 'done'
    return rec

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('count', type=int, nargs='?', default=1)
    ap.add_argument('start', type=int, nargs='?', default=0)
    args = ap.parse_args()
    pool = json.load(open(POOL))
    done = set()
    try:
        for line in open(BANK, encoding='utf-8'):
            r = json.loads(line)
            if r.get('stage') == 'done' or r.get('key'):
                done.add(r['gh_login'])
    except Exception:
        pass
    cand = [a for a in pool if a['login'] not in done]
    log(f'=== xkiro farm: {args.count}, candidates {len(cand)}, TG_ID set: {TG_ID is not None}')
    tgs = tg_sessions(args.count + 2)
    log('tg sessions:', len(tgs))
    n = 0
    for i, a in enumerate(cand[args.start:]):
        if n >= args.count:
            break
        goods = good_sessions()
        if goods:
            tg = goods[n % len(goods)]  # REUSE: proven sessions verify unlimited accounts
        else:
            tgs = tg_sessions(1)  # fresh per account: excludes xkiro-used + miarouter used_tg
            tg = tgs[0] if tgs else None
        log(f'--- {a["login"]} (tg: {os.path.basename(tg) if tg else "NONE"})')
        try:
            rec = farm_one(a, tg)
        except Exception as e:
            rec = {'gh_login': a['login'], 'stage': 'exc', 'err': f'{type(e).__name__}:{e}'[:120]}
        with open(BANK, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        log('   ', {k: (str(v)[:60] if k not in ('cookies',) else '<saved>') for k, v in rec.items() if k != 'gh_login'})
        n += 1
        time.sleep(25)

if __name__ == '__main__':
    main()
