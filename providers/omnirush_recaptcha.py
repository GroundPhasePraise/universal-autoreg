# -*- coding: utf-8 -*-
"""Omnirush.ai autoreg — reversed API (reCAPTCHA v3 via 2captcha + client-signals header).

Flow (from registration-LBv3GV6_.js / omnirush-api-BCDm5SzM.js):
  POST /omnirush/register  {email, display_name, domain, occupation, referral_source,
                            consent_version, accept_consent, captcha_token, password}
    headers: X-OmniRush-Client-Signals: ch=windows&gl=d3d11&font=segoe&touch=0
  -> approval_state approved|pending ; Set-Cookie session
  POST /omnirush/me/verify-email {code}   (6-digit code from mailbox)
  POST /omnirush/me/verify-email/resend   (no body)
  POST /omnirush/activate {token}         (if email carries an activate token)

Usage: python omni_reg.py [count]
"""
import json, sys, time, random, string, re, os
import urllib.request, urllib.error, urllib.parse
import http.cookiejar
import imaplib, email as emaillib

BASE = "https://omnirush.ai"
SITEKEY = "6LcwStMtAAAAAIIYIMlD3G53LRtZcxUE3_BZumMc"
PAGEURL = "https://omnirush.ai/console"
ACTION = "signup"
CONSENT = "2026-10-07"
SIGNALS = "ch=windows&gl=d3d11&font=segoe&touch=0"
POOL = "C:/Users/User/Desktop/avtoreg/working_mails.txt"
STATE = "omni_state.json"
ACC = "omni_accounts.jsonl"
KEY_FILE = "C:/Users/User/tmp/captcha_keys_2captcha.json"
IMAP_HOST = "secureimap.t-online.de"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

OCCUPATIONS = ["Backend developer", "Software engineer", "DevOps engineer",
               "Full-stack developer", "Systems programmer", "ML engineer"]
SOURCES = ["search", "github", "reddit", "hacker news", "a friend"]
DOMAINS = ["software", "devops-sre", "data-ml", "security", "systems-kernel"]


def load_key():
    d = json.load(open(KEY_FILE))
    ks = d["keys"] if isinstance(d, dict) else d
    best, best_bal = None, -1e9
    for k in ks:
        try:
            out = post_form("https://api.2captcha.com/res.php",
                            {"key": k["key"], "action": "getbalance", "json": 1}, timeout=30)
            bal = float(json.loads(out).get("request", -1))
        except Exception:
            bal = -1.0
        print("    key %s balance $%.3f" % (k.get("label"), bal))
        if bal > best_bal:
            best, best_bal = k["key"], bal
    if best_bal < 0.05:
        raise RuntimeError("all 2captcha keys empty (best $%.3f)" % best_bal)
    return best


def post_form(url, data, timeout=60):
    r = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                               headers={"Content-Type": "application/x-www-form-urlencoded",
                                        "User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(r, timeout=timeout).read().decode()


def solve_recaptcha_v3(key, action=ACTION):
    sub = post_form("https://api.2captcha.com/in.php", {
        "key": key, "method": "userrecaptcha", "version": "v3",
        "googlekey": SITEKEY, "pageurl": PAGEURL, "action": action, "json": 1})
    j = json.loads(sub)
    if j.get("status") != 1:
        raise RuntimeError("v3 submit fail: %s" % sub[:200])
    rid = j["request"]
    for _ in range(30):
        time.sleep(7)
        g = post_form("https://api.2captcha.com/res.php",
                      {"key": key, "action": "get", "id": rid, "json": 1})
        gj = json.loads(g)
        if gj.get("status") == 1:
            return gj["request"]
        if "CAPCHA_NOT_READY" in str(gj.get("request", "")):
            continue
        raise RuntimeError("v3 get fail: %s" % g[:200])
    raise RuntimeError("v3 timeout")


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.op.addheaders = [
            ("User-Agent", UA),
            ("Accept", "application/json"),
            ("Accept-Language", "en-US,en;q=0.9"),
            ("Origin", BASE),
            ("Referer", BASE + "/console"),
            ("X-OmniRush-Client-Signals", SIGNALS),
        ]

    def req(self, path, data=None, method=None, timeout=40):
        body = json.dumps(data).encode() if data is not None else None
        r = urllib.request.Request(BASE + path, data=body,
                                   method=method or ("POST" if data is not None else "GET"))
        if body is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with self.op.open(r, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                try:
                    return resp.status, json.loads(raw)
                except Exception:
                    return resp.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw


def imap_wait(email_addr, ipass, timeout=300):
    """Return (code6, activate_token, links) from OmniRush mails."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL(IMAP_HOST)
            m.login(email_addr, ipass)
            m.select("INBOX")
            typ, data = m.search(None, '(SUBJECT "OmniRush")')
            ids = data[0].split() if data and data[0] else []
            for i in ids[-5:]:
                typ, md = m.fetch(i, "(RFC822)")
                if not md or not md[0]:
                    continue
                msg = emaillib.message_from_bytes(md[0][1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/plain", "text/html"):
                            body += part.get_payload(decode=True).decode("utf-8", "replace")
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", "replace")
                code = re.search(r"\b(\d{6})\b", re.sub(r"<[^>]+>", " ", body))
                act = re.search(r"omnirush\.ai/omnirush/activate\?token=([\w.-]+)", body)
                if not act:
                    act = re.search(r"/activate[^\"'\s]*token=([\w.-]+)", body)
                links = re.findall(r"https://omnirush\.ai/[^\s\"'<]+", body)
                if code or act or links:
                    m.logout()
                    return (code.group(1) if code else None,
                            act.group(1) if act else None, links)
            m.logout()
        except Exception as e:
            print("    imap err:", str(e)[:90])
        time.sleep(15)
    return None, None, []


def rnd_name():
    a = random.choice(["Alex", "Max", "Nick", "Ivan", "Oleg", "Dmitry", "Sergey",
                       "Pavel", "Anton", "Kirill", "Victor", "Roman"])
    b = random.choice(["Morgan", "Fischer", "Lang", "Weber", "Keller", "Novak",
                       "Bauer", "Richter", "Wolf", "Stein"])
    return "%s %s" % (a, b)


def one(email_addr, ipass, key):
    c = Client()
    pw = "Om" + "".join(random.choices(string.ascii_letters + string.digits, k=14)) + "3!"
    payload = {
        "email": email_addr,
        "display_name": rnd_name(),
        "domain": random.choice(DOMAINS),
        "occupation": random.choice(OCCUPATIONS),
        "referral_source": random.choice(SOURCES),
        "consent_version": CONSENT,
        "accept_consent": True,
        "password": pw,
    }
    rec = {"email": email_addr, "imap_pass": ipass, "password": pw,
           "display_name": payload["display_name"], "ts": int(time.time())}

    for attempt in range(2):
        t0 = time.time()
        tok = solve_recaptcha_v3(key)
        print("    recaptcha v3 token %d chars in %.0fs" % (len(tok or ""), time.time() - t0))
        payload["captcha_token"] = tok
        st, resp = c.req("/omnirush/register/password", payload)
        print("    register HTTP %s: %s" % (st, str(resp)[:220]))
        code = resp.get("code") if isinstance(resp, dict) else None
        detail = resp.get("detail") if isinstance(resp, dict) else None
        err = code or detail
        if st in (200, 201):
            rec["approval_state"] = resp.get("approval_state") if isinstance(resp, dict) else "?"
            rec["resp"] = resp if isinstance(resp, dict) else str(resp)[:200]
            break
        if err == "captcha_failed" and attempt == 0:
            print("    captcha_failed, retrying with fresh token")
            time.sleep(3)
            continue
        rec["error"] = str(err or resp)[:120]
        return rec
    else:
        return rec

    # email verification
    code6, act_tok, links = imap_wait(email_addr, ipass)
    if code6:
        st, r2 = c.req("/omnirush/me/verify-email", {"code": code6})
        print("    verify-email(%s) HTTP %s: %s" % (code6, st, str(r2)[:120]))
        rec["email_verified"] = st in (200, 201, 204)
    elif act_tok:
        st, r2 = c.req("/omnirush/activate", {"token": act_tok})
        print("    activate HTTP %s: %s" % (st, str(r2)[:120]))
        rec["activated"] = st in (200, 201, 204)
    else:
        print("    no verify mail found; links=%s" % (links[:2],))
        rec["email_verified"] = False
    # check me
    st, me = c.req("/omnirush/me")
    if st == 200 and isinstance(me, dict):
        rec["me"] = {"approval_state": me.get("approval_state"),
                     "email_verified": me.get("email_verified", me.get("verified"))}
        print("    me: %s" % json.dumps(rec["me"]))
    try:
        rec["cookies"] = {ck.name: ck.value for ck in c.cj}
    except Exception:
        pass
    return rec


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    key = load_key()
    pool = []
    for line in open(POOL, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and ":" in line:
            e, p = line.rsplit(":", 1)
            if e.count("-") and re.search(r"-\d{3,}@t-online\.de$", e):
                continue  # dash-aliases dead for delivery
            pool.append((e, p))
    stt = json.load(open(STATE)) if os.path.exists(STATE) else {"idx": 0}
    ok = 0
    while ok < count and stt["idx"] < len(pool):
        email_addr, ipass = pool[stt["idx"]]
        stt["idx"] += 1
        json.dump(stt, open(STATE, "w"))
        print("[%d/%d] %s" % (stt["idx"], len(pool), email_addr))
        try:
            rec = one(email_addr, ipass, key)
        except Exception as e:
            print("    EXC:", str(e)[:200])
            rec = {"email": email_addr, "imap_pass": ipass, "error": str(e)[:200]}
        with open(ACC, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if not rec.get("error"):
            ok += 1
        time.sleep(random.uniform(15, 30))
    print("DONE ok=%d idx=%d" % (ok, stt["idx"]))


if __name__ == "__main__":
    main()
