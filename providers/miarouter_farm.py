
"""miarouter mass autoreg — pool builder. Free turnstile via local sidecar :8877."""
import json, time, secrets, string, urllib.request, urllib.parse, urllib.error, os, sys

BASE = "https://miarouter.online"
SITEKEY = "0x4AAAAAAEj69NaErmbKI26M"
SIDE = "http://127.0.0.1:8879/solve"
AFF = "IDH1"
POOL = r"C:/Users/User/Desktop/farm/miarouter/accounts.jsonl"
STATE = r"C:/Users/User/Desktop/farm/miarouter/farm_state.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
PROXY_FILE = r"C:/Users/User/tmp/mia_proxies.json"
PROXIES = json.load(open(PROXY_FILE)) + ["DIRECT"] if os.path.exists(PROXY_FILE) else ["DIRECT"]
import random
random.shuffle(PROXIES)
_cur_p = {"i": 0, "proxy": PROXIES[0]}

def next_proxy():
    _cur_p["i"] = (_cur_p["i"] + 1) % len(PROXIES)
    _cur_p["proxy"] = PROXIES[_cur_p["i"]]
    return _cur_p["proxy"]

def cur_proxy():
    return _cur_p["proxy"]

os.makedirs(os.path.dirname(POOL), exist_ok=True)

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def solve(url_page="/sign-up"):
    for _try in range(3):
        try:
            p = {"type":"turnstile","url":BASE+url_page,"sitekey":SITEKEY,"real_page":True}
            req = urllib.request.Request(SIDE, data=json.dumps(p).encode(), headers={"Content-Type":"application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=280).read())
            tok = r.get("token") or ""
            if tok:
                return tok
        except Exception as e:
            log("solve retry:", str(e)[:50])
            time.sleep(8)
    return ""

def http(method, path, body=None, jwt=None, raw_body=None, proxy=None):
    url = BASE + path
    data = None
    headers = {"User-Agent":UA, "Origin":BASE, "Referer":BASE+"/sign-up", "Accept":"application/json"}
    if body is not None:
        data = json.dumps(body).encode(); headers["Content-Type"]="application/json"
    if raw_body is not None:
        data = raw_body; headers["Content-Type"]="application/json"
    if jwt: headers["Authorization"] = "Bearer "+jwt
    if proxy is None: proxy = cur_proxy()
    ph = urllib.request.ProxyHandler({} if proxy == "DIRECT" else {"http":proxy,"https":proxy})
    opener = urllib.request.build_opener(ph)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        r = opener.open(req, timeout=12)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        try: return e.code, e.read().decode()
        except: return e.code, ""
    except Exception:
        return 0, "proxy_dead"

def gen_creds():
    alpha = string.ascii_lowercase + string.digits
    u = "refox" + "".join(secrets.choice(alpha) for _ in range(6))
    p = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(13)) + "Aa1"
    return u, p

def make_account(idx):
    u, p = gen_creds()
    proxy = next_proxy()  # sticky per account
    log(idx, "proxy", proxy)
    # 1. register
    for attempt in range(3):
        tok = solve("/sign-up")
        if not tok: log(idx, "solve fail, retry"); time.sleep(5); continue
        st, resp = http("POST", f"/api/user/register?turnstile={urllib.parse.quote(tok)}",
                        body={"username":u,"password":p,"aff_code":AFF,"turnstile":tok,"agreement_confirmed":True}, proxy=proxy)
        try: j = json.loads(resp)
        except: j = {"success":False,"message":resp[:100]}
        if st == 200 and j.get("success"): break
        msg = j.get("message","")
        if st == 0 or resp == "proxy_dead":
            proxy = next_proxy(); log(idx, "proxy dead, rotate ->", proxy); continue
        if st == 429 or "rate" in msg.lower():
            proxy = next_proxy(); log(idx, "429 register, rotate ->", proxy); time.sleep(2); continue
        if "already" in msg.lower() or "exist" in msg.lower():
            u, p = gen_creds(); continue
        log(idx, "reg fail:", st, msg[:120]); time.sleep(5)
    else:
        return None
    log(idx, "REG OK", u)
    # 2. login
    jwt = None
    for attempt in range(4):
        tok2 = solve("/sign-in")
        if not tok2: time.sleep(5); continue
        st, resp = http("POST", f"/api/user/login?turnstile={urllib.parse.quote(tok2)}",
                        body={"username":u,"password":p,"turnstile":tok2}, proxy=proxy)
        try: j = json.loads(resp)
        except: j = {}
        if st == 200 and j.get("success"):
            jwt = j["data"]["access_token"]; break
        if st == 0 or resp == "proxy_dead":
            proxy = next_proxy(); log(idx, "proxy dead, rotate ->", proxy); continue
        if st == 429:
            proxy = next_proxy(); log(idx, "429 login, rotate ->", proxy); time.sleep(2); continue
        log(idx, "login fail:", st, str(j)[:120]); time.sleep(10)
    if not jwt:
        rec = {"username":u,"password":p,"aff":AFF,"status":"reg_ok_login_fail","ts":int(time.time())}
        open(POOL,"a",encoding="utf-8").write(json.dumps(rec)+"\n")
        return rec
    # 3. create token + reveal key
    key = None; tid = None
    st, resp = http("POST", "/api/token/", jwt=jwt, body={"name":"main","remain_quota":500000,"expired_time":-1,"unlimited_quota":True,"model_limits":"","allowed_ips":""})
    if st == 200:
        st2, resp2 = http("GET", "/api/token/?p=0&size=10", jwt=jwt)
        try:
            items = json.loads(resp2)["data"]["items"]
            if items:
                tid = items[0]["id"]
                st3, resp3 = http("POST", f"/api/token/{tid}/key", jwt=jwt, raw_body=b"{}")
                if st3 == 200:
                    key = json.loads(resp3)["data"]["key"]
        except Exception as e:
            log(idx, "key err", e)
    rec = {"username":u,"password":p,"aff":AFF,"jwt":jwt,"token_id":tid,"api_key":("sk-"+key) if key and not key.startswith("sk-") else key,"status":"full","ts":int(time.time())}
    open(POOL,"a",encoding="utf-8").write(json.dumps(rec)+"\n")
    log(idx, "FULL OK", u, "key:", (key or "NONE")[:14]+"...")
    json.dump({"last_idx":idx,"last_user":u,"ts":int(time.time())}, open(STATE,"w"))
    return rec

def main():
    target = int(sys.argv[1]) if len(sys.argv)>1 else 50
    ok = 0
    for i in range(target):
        try:
            r = make_account(i)
            if r and r.get("status")=="full": ok += 1
        except Exception as e:
            log(i, "FATAL", repr(e)[:200])
            time.sleep(20)
        time.sleep(3)
    log("DONE. full accounts:", ok)

if __name__ == "__main__":
    main()
