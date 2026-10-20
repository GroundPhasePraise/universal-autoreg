# cleanapis.com mass reg: GitHub OAuth -> free Starter plan -> api key -> verify -> save
import os
import sys, re, json, time, random, urllib.parse, requests, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from gh_http import GHSession

CID = "Ov23li48tsmVvDWqWfhs"
SCOPE = "user:email,read:user"
GH_POOL = "C:/Users/User/tmp/gh_accounts.json"
OUT = "cleanapis_accounts.jsonl"
USED = "ca_used_gh.txt"
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'}

def load_pool():
    d = json.load(open(GH_POOL, encoding='utf-8'))
    used = set()
    try: used = set(open(USED).read().split())
    except Exception: pass
    return [a for a in d if a.get('login') not in used]

def mark_used(login):
    open(USED, 'a').write(login + '\n')

def reg_one(acc):
    res = {'gh_login': acc['login'], 'ok': False, 'provider': 'github_oauth', 'ts': int(time.time())}
    s = requests.Session(); s.headers.update(UA)
    r = s.get('https://cleanapis.com/auth/github/redirect', allow_redirects=False, timeout=30)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers.get('Location', '')).query)
    state = q.get('state', [None])[0]
    if not state:
        res['err'] = 'no state'; return res
    ghs = GHSession(bind=False)
    ok, msg = ghs.login(acc['login'], acc['password'], acc.get('totp'))
    if not ok:
        res['err'] = 'gh login: ' + str(msg)[:120]; return res
    code, err = ghs.oauth_code(CID, state, scope=SCOPE)
    if not code:
        res['err'] = 'oauth: ' + str(err)[:150]; return res
    cb = s.get('https://cleanapis.com/auth/github/callback?code=%s&state=%s' % (code, state), allow_redirects=True, timeout=40)
    res['cb'] = cb.status_code
    if '/login' in cb.url and 'dashboard' not in cb.url:
        res['err'] = 'callback bounced'; return res
    # activate free starter plan
    g = s.get('https://cleanapis.com/dashboard/get-started?plan=starter', timeout=25)
    csrf = re.findall(r'name="_token" value="([^"]+)"', g.text)
    if csrf:
        act = s.post('https://cleanapis.com/dashboard/billing/checkout/4',
                     data={'_token': csrf[0], 'billing_cycle': 'monthly', 'coupon_code': '', 'payment_method': 'paddle'},
                     allow_redirects=True, timeout=40,
                     headers={'Origin': 'https://cleanapis.com', 'Referer': 'https://cleanapis.com/dashboard/get-started?plan=starter'})
        res['plan_ok'] = 'billing/success' in act.url or 'plan' in act.url
    # create api key
    t = s.get('https://cleanapis.com/dashboard/api-keys', timeout=25)
    csrf2 = re.findall(r'name="_token" value="([^"]+)"', t.text)
    if not csrf2:
        res['err'] = 'no csrf api-keys'; return res
    nm = 'farm%d' % random.randint(10000, 99999)
    cr = s.post('https://cleanapis.com/dashboard/api-keys',
                data={'_token': csrf2[0], 'name': nm, 'scopes[]': ['inference', 'models:read', 'embeddings']},
                allow_redirects=True, timeout=40,
                headers={'Origin': 'https://cleanapis.com', 'Referer': 'https://cleanapis.com/dashboard/api-keys'})
    ids = re.findall(r'api-keys.{0,4}?(\d{4,7}).{0,4}?reveal', cr.text)
    ids = list(dict.fromkeys(ids))
    if not ids:
        res['err'] = 'no key created'; return res
    # reveal newest key (highest id)
    kid = max(ids, key=int)
    rv = s.get('https://cleanapis.com/dashboard/api-keys/%s/reveal' % kid, headers={'Accept': 'application/json'}, timeout=25)
    try: d = rv.json()
    except Exception: res['err'] = 'reveal non-json ' + rv.text[:80]; return res
    if not d.get('ok'):
        res['err'] = 'reveal fail: ' + str(d)[:100]; return res
    k = d['key']
    mr = requests.get('https://cleanapis.com/v1/models', headers={'Authorization': 'Bearer ' + k}, timeout=30)
    res['models'] = mr.status_code
    res['api_key'] = k
    res['key_id'] = kid
    res['ok'] = (mr.status_code == 200)
    mark_used(acc['login'])
    return res

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    pool = load_pool()
    print('pool free:', len(pool), 'start:', start, flush=True)
    okc = fail429 = 0
    for i, acc in enumerate(pool[start:start+n], start=start):
        try:
            r = reg_one(acc)
        except Exception as e:
            r = {'idx': i, 'gh_login': acc.get('login'), 'ok': False, 'err': 'EXC %s: %s' % (type(e).__name__, str(e)[:150])}
        if r.get('ok'): okc += 1
        if '429' in str(r.get('err', '')):
            fail429 += 1
            if fail429 >= 3:
                print('3x429 -> sleep 1800s', flush=True)
                time.sleep(1800); fail429 = 0
        line = json.dumps(r, ensure_ascii=False)
        print('[%d] %s' % (i, line), flush=True)
        open(OUT, 'a', encoding='utf-8').write(line + '\n')
        time.sleep(random.uniform(20, 35))
    print('DONE ok=%d/%d' % (okc, n), flush=True)

if __name__ == '__main__':
    main()
