"""captcha.py — клиент captcha-инфраструктуры.

Два бэкенда:
1. Локальный sidecar (waguriagentic/captcha-solver, http://127.0.0.1:8877) — БЕСПЛАТНО:
   turnstile / recaptcha v2-v3 / hcaptcha / arkose(funcaptcha) / aliyun / geetest и др. (11 типов).
   Запуск sidecar: см. docs/SETUP.md. Для новых версий нужен SOLVER_ALLOW_UNAUTHENTICATED=1.
2. 2captcha fallback (платный) — когда sidecar не справляется (нативный Turnstile под
   siteverify-проверкой, DataDome, press&hold PerimeterX).

Все ключи — из config.json (НЕ хардкодить).
"""
import json, os, time, urllib.request, urllib.parse

CFG_FILE = os.environ.get("UA_CONFIG", os.path.join(os.path.dirname(__file__), "..", "config.json"))
SIDECAR = os.environ.get("UA_SIDECAR", "http://127.0.0.1:8877")


def _cfg():
    if os.path.exists(CFG_FILE):
        return json.load(open(CFG_FILE, encoding="utf-8"))
    return {}


def _post_json(url, payload, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def sidecar_health():
    try:
        with urllib.request.urlopen(SIDECAR + "/health", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def solve_sidecar(captcha_type: str, sitekey: str, pageurl: str, **kw):
    """Решить капчу локальным sidecar'ом (бесплатно).

    captcha_type: turnstile | recaptcha_v2 | recaptcha_v3 | hcaptcha | funcaptcha | ...
    Для recaptcha v3 обязательны: page_action (action сайта, напр. 'signup').
    Для turnstile рекомендуется real_page режим у sidecar'а (REAL_PAGE=1).
    """
    payload = {"type": captcha_type, "sitekey": sitekey, "pageurl": pageurl}
    payload.update(kw)
    return _post_json(SIDECAR + "/solve", payload)


def solve_2captcha(captcha_type: str, sitekey: str, pageurl: str, **kw):
    """2captcha fallback. ВАЖНО: submit СТРОГО на in.php (res.php = ERROR_EMPTY_METHOD),
    баланс СТРОГО POST api.2captcha.com/res.php (GET = ложный ERROR_WRONG_USER_KEY)."""
    key = _cfg().get("twocaptcha_key")
    if not key:
        raise RuntimeError("twocaptcha_key not set in config.json")
    method = {"turnstile": "turnstile", "recaptcha_v2": "userrecaptcha",
              "recaptcha_v3": "recaptcha", "hcaptcha": "hcaptcha",
              "funcaptcha": "funcaptcha"}.get(captcha_type, captcha_type)
    params = {"key": key, "method": method, "googlekey" if method == "userrecaptcha" else "sitekey": sitekey,
              "pageurl": pageurl, "json": 1}
    params.update(kw)
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen("https://api.2captcha.com/in.php", data=data, timeout=30) as r:
        resp = json.loads(r.read().decode())
    if resp.get("status") != 1:
        raise RuntimeError(f"2captcha submit failed: {resp}")
    cid = resp["request"]
    for _ in range(60):
        time.sleep(5)
        q = urllib.parse.urlencode({"key": key, "action": "get", "id": cid, "json": 1}).encode()
        with urllib.request.urlopen("https://api.2captcha.com/res.php", data=q, timeout=30) as r:
            resp = json.loads(r.read().decode())
        if resp.get("status") == 1:
            return {"token": resp["request"]}
        if resp.get("request") != "CAPCHA_NOT_READY":
            raise RuntimeError(f"2captcha: {resp}")
    raise TimeoutError("2captcha timeout 300s")


def solve(captcha_type: str, sitekey: str, pageurl: str, prefer="sidecar", **kw):
    """Умный решатель: sidecar → при ошибке 2captcha (если включён fallback)."""
    if prefer == "sidecar":
        try:
            return solve_sidecar(captcha_type, sitekey, pageurl, **kw)
        except Exception:
            if _cfg().get("twocaptcha_fallback", True):
                return solve_2captcha(captcha_type, sitekey, pageurl, **kw)
            raise
    return solve_2captcha(captcha_type, sitekey, pageurl, **kw)


def balance_2captcha():
    key = _cfg().get("twocaptcha_key")
    if not key:
        return None
    data = urllib.parse.urlencode({"key": key, "action": "getbalance"}).encode()
    with urllib.request.urlopen("https://api.2captcha.com/res.php", data=data, timeout=15) as r:
        return json.loads(r.read().decode())


if __name__ == "__main__":
    print("sidecar health:", sidecar_health())
    print("2captcha balance:", balance_2captcha())
