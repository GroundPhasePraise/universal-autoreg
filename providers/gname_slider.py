# Gname.com autoreg: playwright chromium + trusted slider drag + IMAP code
import sys, os, re, json, time, random, string, imaplib, email as eml
from playwright.sync_api import sync_playwright

BASE = r"C:/Users/User/tmp/gname_reg"
os.makedirs(BASE, exist_ok=True)
fp = open(r"C:/Users/User/tmp/viktor/fwd_probe.py", encoding="utf-8").read()
GM = re.search(r'GM = "([^"]+)"', fp).group(1)
GP = os.environ.get("GM_APPPW") or re.search(r'GM_APPPW", "([^"]+)"', fp).group(1)

def dot_variant(local="YOUR_EMAIL_LOCAL", domain="gmail.com"):
    # random 1-2 dots inserted -> same Gmail inbox, unique for site
    idxs = sorted(random.sample(range(1, len(local)), random.choice([1, 2])))
    out = ""
    for i, ch in enumerate(local):
        if i in idxs:
            out += "."
        out += ch
    return out + "@" + domain

def canon(addr):
    addr = addr.lower().strip().strip("<>")
    lp, _, dm = addr.partition("@")
    lp = lp.split("+")[0].replace(".", "")
    return lp + "@" + dm

POOL_F = r"C:/Users/User/Desktop/avtoreg/working_mails.txt"
USED_F = os.path.join(BASE, "tonline_used.txt")
def next_tonline():
    used = set()
    if os.path.exists(USED_F):
        used = set(x.strip().lower() for x in open(USED_F) if x.strip())
    for ln in open(POOL_F, encoding="utf-8", errors="ignore"):
        ln = ln.strip()
        if not ln or ln.startswith("#") or ":" not in ln:
            continue
        e, p = ln.split(":", 1)
        e = e.strip().lower()
        # canonical only: dash-aliases (-NNNN@) dead for delivery
        if "-" in e.split("@")[0] or e in used:
            continue
        with open(USED_F, "a") as f:
            f.write(e + "\n")
        return e, p.strip()
    return None, None

EMAIL = sys.argv[1] if len(sys.argv) > 1 else None
TONLINE_PW = None
if EMAIL is None:
    EMAIL, TONLINE_PW = next_tonline()
    if not EMAIL:
        print("POOL EXHAUSTED", flush=True)
        sys.exit(3)
IS_TONLINE = EMAIL.endswith("t-online.de")
PASSWORD = "Bea" + "rer" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "a1!"
STATE = {"email": EMAIL, "password": PASSWORD, "stage": "start"}
def save():
    json.dump(STATE, open(os.path.join(BASE, "gname_state.json"), "w"), indent=1)
save()

def log(*a):
    print(*a, flush=True)

def imap_code(wait=240):
    t0 = time.time()
    while time.time() - t0 < wait:
        try:
            if IS_TONLINE:
                m = imaplib.IMAP4_SSL("secureimap.t-online.de", 993)
                m.login(EMAIL, TONLINE_PW)
                typ, cnt = m.select("INBOX")
                n = int(cnt[0]) if cnt and cnt[0] else 0
                ids = [str(i) for i in range(max(1, n - 29), n + 1)] if n else []
            else:
                m = imaplib.IMAP4_SSL("imap.gmail.com")
                m.login(GM, GP)
                m.select("INBOX")
                since = time.strftime("%d-%b-%Y", time.localtime(time.time() - 86400))
                typ, data = m.search(None, '(SINCE %s)' % since)
                ids = data[0].split()[-40:]
            for i in reversed(ids):
                typ, md = m.fetch(i, "(RFC822)")
                raw = md[0][1]
                msg = eml.message_from_bytes(raw)
                to = (msg.get("To", "") + " " + msg.get("X-Gmail-Original-To", "") + " " + msg.get("Delivered-To", "")).lower()
                frm = (msg.get("From", "") or "").lower()
                addrs = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", to)
                if IS_TONLINE:
                    hit = any(a.lower() == EMAIL.lower() for a in addrs) or not addrs
                else:
                    hit = any(canon(a) == canon(EMAIL) for a in addrs)
                if ("gname" in frm or "gname" in (msg.get("Subject", "") or "").lower()) and hit:
                    body = ""
                    if msg.is_multipart():
                        for p in msg.walk():
                            if p.get_content_type() == "text/plain":
                                body = p.get_payload(decode=True).decode("utf-8", "ignore")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", "ignore")
                    body_html = ""
                    if msg.is_multipart():
                        for p in msg.walk():
                            if p.get_content_type() == "text/html":
                                body_html = p.get_payload(decode=True).decode("utf-8", "ignore")
                    mm = re.search(r"\b(\d{4,8})\b", body) or re.search(r"(?:code|验证码)[^\d]{0,40}(\d{4,8})", body_html, re.I) or re.search(r"\b(\d{6})\b", body_html)
                    m.logout()
                    if mm:
                        return mm.group(1)
            m.logout()
        except Exception as e:
            log("imap err:", e)
        time.sleep(6)
    return None

def human_drag(page, sel_bar=".gn-slide-bar", sel_rail=".gn-slide-rail"):
    rect = page.evaluate("""(sel) => {
        const bars = [...document.querySelectorAll(sel[0])].filter(b => b.offsetParent !== null && b.getBoundingClientRect().width > 10);
        const rails = [...document.querySelectorAll(sel[1])].filter(r => r.offsetParent !== null);
        if (!bars.length) return null;
        const b = bars[bars.length - 1].getBoundingClientRect();
        const r = (rails[rails.length - 1] || bars[bars.length - 1]).getBoundingClientRect();
        return {bx: b.x, by: b.y, bw: b.width, bh: b.height, rw: r.width};
    }""", [sel_bar, sel_rail])
    if not rect:
        return "no-visible-bar"
    dist = rect["rw"] - rect["bw"] + 40  # OVERSHOOT: widget clamps delta at config width; must saturate
    x0 = rect["bx"] + rect["bw"] / 2
    y0 = rect["by"] + rect["bh"] / 2
    page.mouse.move(x0 + random.uniform(-3, 3), y0 + random.uniform(-4, 4))
    time.sleep(random.uniform(0.08, 0.2))
    page.mouse.move(x0, y0)
    time.sleep(random.uniform(0.05, 0.12))
    page.mouse.down()
    time.sleep(random.uniform(0.1, 0.25))
    steps = random.randint(24, 32)
    for i in range(1, steps + 1):
        p = i / steps
        ease = 1 - (1 - p) ** 3
        x = x0 + dist * ease + random.uniform(-1.2, 1.2)
        y = y0 + random.uniform(-2.5, 2.5)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.014, 0.038))
    for _ in range(4):  # saturate past the end so clamped delta reaches max
        page.mouse.move(x0 + dist + random.uniform(-2, 4), y0 + random.uniform(-2, 2))
        time.sleep(0.05)
    page.mouse.move(x0 + dist, y0)
    time.sleep(random.uniform(0.08, 0.18))
    page.mouse.up()
    st = ""
    for _ in range(10):
        time.sleep(0.6)
        st = page.evaluate("""() => {
            try {
                const a = window.GN_SLIDER_VERIFY ? window.GN_SLIDER_VERIFY.status : '';
                const b = window.GN_SLIDER_VERIFY_LOGIN ? window.GN_SLIDER_VERIFY_LOGIN.status : '';
                return a + '|' + b;
            } catch(e){ return 'err'; }
        }""")
        if "success" in st or "error" in st or "fail" in st:
            break
    bx_after = page.evaluate("""(sel) => { const bars=[...document.querySelectorAll(sel)].filter(b=>b.offsetParent!==null); return bars.length? Math.round(bars[bars.length-1].getBoundingClientRect().x) : -1; }""", sel_bar)
    return "dragged %.0fpx bar_after_x=%s widget_status=%s" % (dist, bx_after, st)

with sync_playwright() as pw:
    try:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    except Exception as e:
        log("launch err, retry explicit path:", str(e)[:200])
        cand = [d for d in os.listdir(r"C:/Users/User/AppData/Local/ms-playwright") if d.startswith("chromium-1")]
        exe = os.path.join(r"C:/Users/User/AppData/Local/ms-playwright", sorted(cand)[-1], "chrome-win", "chrome.exe")
        browser = pw.chromium.launch(headless=True, executable_path=exe, args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 900},
        locale="en-US",
        timezone_id="Europe/Kiev",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    )
    page = ctx.new_page()
    page.add_init_script("""
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.__EVTLOG = [];
(function(){
    const oel = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(t, f, o) {
        try {
            let d = 'unknown';
            if (this === window) d = 'window';
            else if (this === document) d = 'document';
            else if (this.nodeType === 1) d = this.tagName + '.' + String(this.className && this.className.baseVal !== undefined ? this.className.baseVal : this.className).slice(0, 60);
            if (['mousedown','mousemove','mouseup','touchstart','touchmove','touchend','pointerdown','pointermove','pointerup','click'].indexOf(t) >= 0)
                window.__EVTLOG.push(d + ' :: ' + t);
        } catch (e) {}
        return oel.call(this, t, f, o);
    };
})();
""")
    reqlog = []
    def on_resp(r):
        if "/request/" in r.url:
            try:
                reqlog.append({"url": r.url, "status": r.status, "body": r.text()[:400]})
                log("NET", r.status, r.url.split("gname.com")[-1][:60], r.text()[:150].replace("\n", " "))
            except Exception:
                pass
    page.on("response", on_resp)
    page.goto("https://www.gname.com/register", wait_until="domcontentloaded", timeout=60000)
    time.sleep(3)
    log("title:", page.title())
    STATE["stage"] = "page-loaded"
    save()

    # fill form
    page.fill("input[name=re_yx]", EMAIL)
    time.sleep(random.uniform(0.3, 0.7))
    page.fill("input[name=re_mm]", PASSWORD)
    time.sleep(random.uniform(0.3, 0.7))
    page.fill("input[name=re_mm2]", PASSWORD)
    ck = page.query_selector("input[name=re_ty]")
    if ck and not ck.is_checked():
        try:
            ck.click(force=True)
        except Exception:
            page.evaluate("document.querySelector('input[name=re_ty]').click()")
    log("form filled")

    # embedded slider first?
    rail = page.query_selector(".gn-slide-rail")
    if rail and rail.is_visible():
        log("embedded rail visible -> drag")
        log(human_drag(page))
        time.sleep(3)
        yz = page.evaluate("() => (document.querySelector('input[name=re_yzm]')||{}).value || ''")
        tip = page.evaluate("() => { const t=document.querySelector('.gn-slide-tip'); return t?t.innerText.trim():''; }")
        log("re_yzm:", yz[:40], "tip:", tip[:60])
        evt = page.evaluate("() => JSON.stringify([...new Set(window.__EVTLOG)])")
        log("EVTLOG:", evt[:2200])
        STATE["slider_embed"] = {"re_yzm": yz[:60], "tip": tip}
        save()
        page.screenshot(path=os.path.join(BASE, "step1_embed.png"))

    # click Send Code
    btn = page.query_selector('.login-yzm-btn[data-lx="reg"]') or page.query_selector(".login-yzm-btn")
    if btn:
        btn.click()
        log("send-code clicked")
    else:
        page.evaluate("""() => { const els=[...document.querySelectorAll('div,span')].filter(e=>(e.innerText||'').trim()==='Send Code'); if(els.length) els[els.length-1].click(); }""")
        log("send-code via text")
    # popup slider may appear (server demands lx=reg slider for send_email)
    for attempt in range(4):
        time.sleep(3)
        popup = page.evaluate("""() => {
            const p = document.querySelector('#pop-txyz');
            let pst = '';
            try { pst = window.GN_SLIDER_VERIFY ? window.GN_SLIDER_VERIFY.status : ''; } catch(e){}
            const rails = [...document.querySelectorAll('.gn-slide-rail')].filter(r => r.offsetParent !== null);
            return {pop: !!(p && p.offsetParent !== null) || !!document.querySelector('#pop-txyz .gn-slide-bar'), pst: pst, n: rails.length};
        }""")
        yz = page.evaluate("() => (document.querySelector('input[name=re_yzm]')||{}).value || ''")
        sent = any(e.get("body", "").find('"code":1') >= 0 and "send_email" in e["url"] for e in reqlog)
        log("attempt", attempt, popup, "re_yzm:", yz[:20], "send_email ok:", sent)
        if sent:
            break
        if popup.get("pop") and popup.get("pst") != "success":
            try:
                log("POPUP DRAG:", human_drag(page, sel_bar="#pop-txyz .gn-slide-bar", sel_rail="#pop-txyz .gn-slide-rail"))
                time.sleep(4)
            except Exception as e:
                log("popup drag err:", e)
        page.screenshot(path=os.path.join(BASE, "step2_send%d.png" % attempt))
    STATE["stage"] = "send-code-done"
    STATE["net"] = reqlog[-8:]
    save()

    # IMAP code
    code = imap_code()
    log("email code:", code)
    if not code:
        STATE["stage"] = "no-email-code"
        save()
        browser.close()
        sys.exit(2)
    filled = False
    for fn in ("yx_yzm", "re_yzm", "eyzm"):
        try:
            el = page.query_selector("input[name=%s]" % fn)
            if el:
                el.fill(code)
                log("code filled into", fn)
                filled = True
                break
        except Exception:
            pass
    if not filled:
        log("WARN: no code field found")

    # submit register
    page.evaluate("""() => {
        const b = document.querySelector('form.gm-form button.login-btn[type=submit]') ||
            [...document.querySelectorAll('button,div.gm-btn,div[class*=btn],span')].filter(e => e.offsetParent !== null && /^(Register|Sign ?up|Create)/i.test((e.innerText||'').trim()))[0];
        if (b) b.click();
    }""")
    # wait for navigation to dashboard (auto-login after successful reg)
    reg_ok = False
    uid = ""
    for _ in range(20):
        time.sleep(2)
        try:
            u = page.url
            if "/register" not in u:
                reg_ok = True
                break
            # sometimes dashboard content loads under same url; check for UID marker
            uid_t = page.evaluate("() => { const m = document.body.innerText.match(/UID[:\\s]*(\\d{4,9})/); return m ? m[1] : ''; }")
            if uid_t:
                reg_ok = True
                uid = uid_t
                break
        except Exception:
            pass
    if reg_ok and not uid:
        try:
            uid = page.evaluate("() => { const m = document.body.innerText.match(/UID[:\\s]*(\\d{4,9})/); return m ? m[1] : ''; }") or ""
        except Exception:
            pass
    reg_resp = [e for e in reqlog if "p_reg" in e["url"] or "reg" in e["url"].split("/request/")[-1][:8]]
    log("REG_OK:", reg_ok, "UID:", uid, "url:", page.url)
    log("p_reg:", json.dumps([e for e in reqlog if "p_reg" in e["url"]])[:500])
    STATE["stage"] = "registered" if reg_ok else "reg-submitted"
    STATE["uid"] = uid
    STATE["p_reg"] = reg_resp[-2:]
    STATE["url"] = page.url
    save()
    if reg_ok:
        rec = {"site": "gname.com", "email": EMAIL, "password": PASSWORD, "uid": uid,
               "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "url": page.url}
        with open(os.path.join(BASE, "gname_accounts.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        log("BANK APPENDED", EMAIL)
    page.screenshot(path=os.path.join(BASE, "step3_result.png"), full_page=False)
    browser.close()
    log("DONE", STATE["stage"])
