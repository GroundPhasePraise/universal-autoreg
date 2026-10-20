# llmtr.com mass autoreg — turnstile via free sidecar :8877, gmail +alias IMAP OTP
import json, time, re, random, string, sys, os, urllib.request, urllib.error, http.cookiejar, imaplib, email

BASE = "https://llmtr.com"
SITEKEY = "0x4AAAAAAC_o7kdbb_hnqKdy"
SIDE = "http://127.0.0.1:8877/solve"
OUT = r"C:/Users/User/tmp/llmtr/accounts.jsonl"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"

# gmail imap
GM_USER = "YOUR_EMAIL@gmail.com"
GM_PASS = os.environ.get("GM_PASS", "YOUR_IMAP_APP_PASSWORD")

NAMES = [("Kerem","Yilmaz"),("Emre","Kaya"),("Burak","Demir"),("Cem","Sahin"),("Onur","Aydin"),
         ("Mert","Ozturk"),("Tolga","Arslan"),("Baran","Koc"),("Deniz","Polat"),("Serkan","Bulut")]

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def solve(url_page="/register"):
    for _ in range(3):
        try:
            p = {"type":"turnstile","url":BASE+url_page,"sitekey":SITEKEY,"real_page":True}
            req = urllib.request.Request(SIDE, data=json.dumps(p).encode(), headers={"Content-Type":"application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=280).read())
            tok = r.get("token") or ""
            if tok: return tok
        except Exception as e:
            log("solve retry:", str(e)[:80]); time.sleep(5)
    return ""

def sess():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent",UA),("Accept","application/json")]
    return op

def api(op, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE+path, data=data, method=method)
    req.add_header("Origin", BASE)
    req.add_header("Referer", BASE+"/register")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        r = op.open(req, timeout=60)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, {"raw":"?"}

def gen_pass():
    up = random.choice(string.ascii_uppercase)
    dg = random.choice(string.digits)
    rest = "".join(random.choice(string.ascii_lowercase+string.digits) for _ in range(10))
    p = list(up+dg+rest); random.shuffle(p)
    return "".join(p)

def wait_otp_gmail(alias_tag, since_ts, timeout=180):
    # gmail: mail for YOUR_EMAIL+llmtrN@gmail.com lands in base inbox
    t0 = time.time()
    while time.time()-t0 < timeout:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            m.login(GM_USER, GM_PASS)
            m.select("INBOX")
            _, ids = m.search(None, "(ALL)")
            idl = ids[0].split()[-25:]
            for i in reversed(idl):
                _, msg = m.fetch(i, "(RFC822)")
                raw = msg[0][1]
                em = email.message_from_bytes(raw)
                dt = email.utils.parsedate_to_datetime(em.get("Date",""))
                if dt.timestamp() < since_ts - 30: continue
                to = em.get("To","")
                if alias_tag not in to: continue
                body = ""
                if em.is_multipart():
                    for part in em.walk():
                        if part.get_content_type()=="text/plain":
                            body = part.get_payload(decode=True).decode(errors="replace"); break
                else:
                    body = em.get_payload(decode=True).decode(errors="replace")
                codes = re.findall(r"\b(\d{6})\b", body)
                if codes:
                    m.logout()
                    return codes[0]
            m.logout()
        except Exception as e:
            log("imap:", str(e)[:60])
        time.sleep(8)
    return ""

def register_one(idx):
    tag = f"llmtr{idx}{random.randint(10,99)}"
    em_addr = f"YOUR_EMAIL+{tag}@gmail.com"
    fn, ln = random.choice(NAMES)
    full = f"{fn} {ln}"
    pw = gen_pass()
    log(f"[{idx}] email={em_addr}")
    tok = solve()
    if not tok: log(f"[{idx}] CAPTCHA FAIL"); return None
    log(f"[{idx}] turnstile ok ({len(tok)})")
    op = sess()
    since = time.time()
    st, r = api(op, "POST", "/api/auth/register", {"fullName":full,"email":em_addr,"password":pw,"captchaToken":tok})
    log(f"[{idx}] register -> {st} {json.dumps(r)[:200]}")
    if st not in (200,201): return None
    try: ct = r["data"]["challengeToken"]
    except Exception: log(f"[{idx}] no challengeToken"); return None
    code = wait_otp_gmail(tag, since)
    if not code: log(f"[{idx}] OTP TIMEOUT"); return None
    log(f"[{idx}] otp={code}")
    st2, r2 = api(op, "POST", "/api/auth/register/verify", {"challengeToken":ct,"code":code})
    log(f"[{idx}] verify -> {st2} {json.dumps(r2)[:300]}")
    if st2 not in (200,201): return None
    rec = {"email":em_addr,"password":pw,"fullName":full,"ts":int(time.time())}
    # whoami
    st3, r3 = api(op, "GET", "/api/auth/me")
    if st3 == 200: rec["me"] = r3.get("data")
    # create key
    st4, r4 = api(op, "POST", "/api/keys", {"name":"main"})
    log(f"[{idx}] create key -> {st4} {json.dumps(r4)[:300]}")
    if st4 in (200,201):
        try: rec["apiKey"] = r4["data"]["apiKey"]; rec["keyId"] = r4["data"]["key"].get("id")
        except Exception: rec["key_raw"] = r4
    with open(OUT,"a",encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False)+"\n")
    log(f"[{idx}] DONE {em_addr} key={rec.get('apiKey','?')[:20] if rec.get('apiKey') else 'NONE'}")
    return rec

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv)>1 else 1
    start = int(sys.argv[2]) if len(sys.argv)>2 else 1
    ok = 0
    for i in range(start, start+n):
        r = register_one(i)
        if r: ok += 1
        if i < start+n-1: time.sleep(random.randint(15,30))
    log(f"RESULT {ok}/{n}")
