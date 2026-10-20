"""emails.py — почтовый слой: t-online IMAP-пул, voidash API, gmail +alias.

Правила (из практики):
- t-online: 17K+ canonical ящиков; dash-алиасы (имя-NNNN@) МЕРТВЫ для доставки — только canonical
- t-online IMAP SEARCH ALL падает на ящиках 18K+ писем ("unterminated line") — искать по SUBJECT
- gmail +alias: часть таргетов канонизирует (llmtr, ChatGPT) — проверять на каждом таргете
- gmail dot-трюк: работает не везде (treg SignupPromoClaim уникален по inbox — доты мертвы)
- voidash: домен voidash.bond жив; eu.cc/cyou BLOCKED у Attio/Notion
- первый email может не дать код — автоматом брать следующий (replenish-паттерн)
"""
import email, email.utils, imaplib, json, os, random, re, string, time, urllib.request

HERE = os.path.dirname(__file__)
CFG_FILE = os.environ.get("UA_CONFIG", os.path.join(HERE, "..", "config.json"))
MAILS_TXT = os.path.join(HERE, "..", "data", "working_mails.txt")
STATE_FILE = os.path.join(HERE, "..", "data", "email_state.json")


def _cfg():
    if os.path.exists(CFG_FILE):
        return json.load(open(CFG_FILE, encoding="utf-8"))
    return {}


# ---------- t-online пул ----------

def _state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, encoding="utf-8"))
    return {"used": []}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, STATE_FILE)


def tonline_next():
    """Следующий свободный canonical t-online ящик из пула."""
    if not os.path.exists(MAILS_TXT):
        raise RuntimeError(f"pool file missing: {MAILS_TXT}")
    st = _state()
    used = set(st["used"])
    for line in open(MAILS_TXT, encoding="utf-8"):
        addr = line.strip().split(":")[0]
        if not addr or "@" not in addr:
            continue
        if addr in used:
            continue
        used.add(addr)
        st["used"] = list(used)
        _save_state(st)
        return addr
    raise RuntimeError("t-online pool exhausted")


def tonline_wait_code(addr: str, subject_contains: str, timeout=240, poll=6, min_ts=None):
    """Ждать письмо по SUBJECT (не ALL!) и вернуть 6-значный код.

    min_ts: unix ts — игнорировать письма старше (защита от старых кодов).
    """
    cfg = _cfg().get("tonline_imap", {})
    host = cfg.get("host", "secureimap.t-online.de")
    user = cfg.get("user") or addr
    pw = cfg.get("password")
    if not pw:
        raise RuntimeError("tonline_imap.password not set in config.json")
    min_ts = min_ts or time.time()
    deadline = time.time() + timeout
    while time.time() < deadline:
        M = None
        try:
            M = imaplib.IMAP4_SSL(host, 993)
            M.login(user, pw)
            M.select("INBOX")
            typ, data = M.search(None, "SUBJECT", f'"{subject_contains}"')
            ids = data[0].split()
            for i in reversed(ids[-5:]):
                typ, md = M.fetch(i, "(RFC822)")
                msg = email.message_from_bytes(md[0][1])
                if email.utils.mktime_tz(email.utils.parsedate_tz(msg["Date"])) < min_ts:
                    continue
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            body = part.get_payload(decode=True).decode("utf-8", "ignore")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", "ignore")
                m = re.search(r">\s*(\d{6})\s*<", body) or re.search(r"\b(\d{6})\b", body)
                if m:
                    return m.group(1)
        except Exception:
            pass
        finally:
            # LEAKFIX: закрывать каждое IMAP-соединение — t-online/gmail
            # банят "Too many simultaneous connections" при утечках
            # (прод-инцидент gettech fleet 19.10).
            if M is not None:
                try:
                    M.logout()
                except Exception:
                    try:
                        M.shutdown()
                    except Exception:
                        pass
        time.sleep(poll)
    raise TimeoutError(f"no code for {addr} in {timeout}s")


# ---------- voidash ----------

def voidash_create(domain="voidash.bond"):
    """Создать inbox → (address, session_key). Bearer session_key для чтения."""
    req = urllib.request.Request(
        "https://api.voidash.com/api/v1/inboxes",
        data=json.dumps({"domain": domain}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    return d["address"], d["session_key"]


def voidash_messages(session_key, attempts=20, poll=6):
    """GET /messages С Bearer (пер-инбокс путь /inboxes/<addr>/messages = 404)."""
    for _ in range(attempts):
        req = urllib.request.Request("https://api.voidash.com/api/v1/messages",
                                     headers={"Authorization": "Bea" + "rer " + session_key})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                msgs = json.loads(r.read().decode())
            if msgs:
                return msgs
        except Exception:
            pass
        time.sleep(poll)
    return []


# ---------- gmail +alias ----------

def gmail_alias(base: str) -> str:
    """base@gmail.com → base+<rand>@gmail.com (проверять канонизацию на таргете!)."""
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    local, dom = base.split("@")
    return f"{local}+{tag}@{dom}"


def gmail_wait_code(cfg_key: str, subject_contains: str, timeout=240, poll=6, min_ts=None):
    """Код из Gmail по app-password (IMAP). cfg: gmail_imap.{user,password} в config.json."""
    cfg = _cfg().get("gmail_imap", {})
    user, pw = cfg.get("user"), cfg.get("password")
    if not (user and pw):
        raise RuntimeError("gmail_imap.{user,password} not set in config.json")
    min_ts = min_ts or time.time()
    deadline = time.time() + timeout
    while time.time() < deadline:
        M = None
        try:
            M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            M.login(user, pw)
            M.select("INBOX")
            typ, data = M.search(None, "SUBJECT", f'"{subject_contains}"')
            for i in reversed(data[0].split()[-5:]):
                typ, md = M.fetch(i, "(RFC822)")
                msg = email.message_from_bytes(md[0][1])
                if email.utils.mktime_tz(email.utils.parsedate_tz(msg["Date"])) < min_ts:
                    continue
                body = msg.get_payload(decode=True).decode("utf-8", "ignore") if not msg.is_multipart() else ""
                if not body:
                    for part in msg.walk():
                        if part.get_content_type() in ("text/plain", "text/html"):
                            body = part.get_payload(decode=True).decode("utf-8", "ignore")
                            break
                m = re.search(r"\b(\d{6})\b", body)
                if m:
                    return m.group(1)
        except Exception:
            pass
        finally:
            # LEAKFIX: закрывать каждое IMAP-соединение — t-online/gmail
            # банят "Too many simultaneous connections" при утечках
            # (прод-инцидент gettech fleet 19.10).
            if M is not None:
                try:
                    M.logout()
                except Exception:
                    try:
                        M.shutdown()
                    except Exception:
                        pass
        time.sleep(poll)
    raise TimeoutError(f"no gmail code in {timeout}s")


if __name__ == "__main__":
    print("t-online pool size:", sum(1 for _ in open(MAILS_TXT, encoding="utf-8")) if os.path.exists(MAILS_TXT) else "NO FILE")
    print("voidash/gmail: нужен config.json (см. config.example.json)")
