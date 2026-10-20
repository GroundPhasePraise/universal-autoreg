# -*- coding: utf-8 -*-
"""secondno_sms.py — 2nd-no.com (2no.pl) free Polish SMS numbers as a UA provider.

Contract:
  python providers/secondno_sms.py N [--gmail]        # register N fresh accounts + first number
  python providers/secondno_sms.py reserve <email> <pass> <reserve_file> <code_file> [timeout] [min_ts]
                                                      # REUSE-FIRST reserve + OTP poll (phone gate)
  python providers/secondno_sms.py accounts           # dump known accounts (data/secondno/state.json)

What it is: 2nd-no.com gives each account 3 free PL numbers for 3 days (renewed on
SMS receipt). Numbers are reserved via 2no.pl JSON-RPC (x-auth-token from the web
session); reservation may demand a Cloudflare Turnstile token — solved FREE by the
captcha sidecar (:8877) or by 2captcha (env TWOCAPTCHA_API_KEY / data/captcha_keys.json).

Register mode uses playwright (login wall is a React SPA) — run under Python 3.11
with PYTHONPATH="" on Windows. Accounts land in data/secondno/state.json AND in the
shared bank (data/bank.jsonl, provider="secondno").

Reserve mode is the phone-gate helper other providers call (e.g. type_workos):
writes {"phone","number_id","expires"} to reserve_file ASAP, then polls SMS and
writes {"code","text","ts"} to code_file (or {"code":null,"err":...}).
REUSE-FIRST: active unused reservations are reused before burning a turnstile solve
(3-number cap per account); used_numbers.json next to reserve_file tracks numbers
that already delivered an OTP — a number is marked used ONLY after a real code.
min_ts: ignore SMS older than this ISO-timestamp prefix (stale-code guard).

NOTE: the free pool is burned for Telegram registrations (BANNED_NUMBER); it works
for web services with lax VOIP filters (type.com, gitlab, dust, prompt.ql.app...).
"""
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

UA_HOME = os.environ.get("UA_HOME") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECONDNO_HOME", os.path.join(UA_HOME, "data", "secondno"))


def _bank_add(rec):
    try:
        from bank import add
        return add(rec)
    except Exception as e:
        print("bank add err:", str(e)[:80], flush=True)
        return False


def mode_register(n, gmail=False):
    from secondno import full_cycle, GmailForwardInbox
    inbox_factory = GmailForwardInbox if gmail else None
    results = full_cycle(n, inbox_factory=inbox_factory)
    ok = 0
    for r in results:
        print(json.dumps(r, ensure_ascii=False), flush=True)
        if r.get("error"):
            continue
        ok += 1
        _bank_add({"provider": "secondno", "email": r.get("email"),
                   "password": r.get("password"),
                   "extra": {"phone": r.get("full"), "number_id": r.get("number_id"),
                             "expires": r.get("expires")}})
    print(f"DONE {ok}/{n} accounts registered", flush=True)
    sys.exit(0 if ok else 1)


def mode_reserve(argv):
    from secondno import SecondNo, get_solver
    email, password, reserve_file, code_file = argv[0:4]
    poll_timeout = int(argv[4]) if len(argv) > 4 else 300
    min_ts = argv[5] if len(argv) > 5 else None
    try:
        solver = get_solver()
    except Exception as e:
        print("solver init err:", e, flush=True)
        solver = None
    sn = SecondNo(solver=solver)
    try:
        sn.login(email, password)
        used_file = os.path.join(os.path.dirname(os.path.abspath(reserve_file)),
                                 "used_numbers.json")
        used = set()
        try:
            used = set(json.load(open(used_file, encoding="utf-8")))
        except Exception:
            pass
        info = None
        try:
            info = sn.reuse_active(used)
            if info:
                print("REUSE active number", info["full"], info["number_id"], flush=True)
        except Exception as e:
            print("reuse scan err:", str(e)[:100], flush=True)
        if not info:
            try:
                info = sn.get_number()
            except Exception as e:
                print("reserve fresh failed:", str(e)[:150], flush=True)
        if not info:
            raise RuntimeError("no free/reservable number (limit reached, all used)")
        phone, number_id = info["full"], info["number_id"]
        with open(reserve_file, "w", encoding="utf-8") as f:
            json.dump({"phone": phone, "number_id": number_id,
                       "expires": info.get("expires")}, f)
        print("RESERVED", phone, number_id, flush=True)

        deadline = time.time() + poll_timeout
        while time.time() < deadline:
            try:
                msgs = sn.read_sms(phone, number_id, timeout=16, poll=8)
                cands = []
                for m in msgs:
                    text = str(m.get("text") or m.get("body") or "")
                    ts = str(m.get("created_at") or m.get("date") or m.get("time") or "")
                    if min_ts and ts and ts < min_ts:
                        continue
                    mm = re.search(r"\b(\d{4,8})\b", text)
                    if mm:
                        cands.append((ts, mm.group(1), text))
                if cands:
                    cands.sort()
                    ts, code, text = cands[-1]
                    with open(code_file, "w", encoding="utf-8") as f:
                        json.dump({"code": code, "text": text[:250], "ts": ts}, f,
                                  ensure_ascii=False)
                    digits = re.sub(r"\D", "", str(phone))
                    used.add(digits[2:] if digits.startswith("48") else digits)
                    try:
                        json.dump(sorted(used), open(used_file, "w", encoding="utf-8"))
                    except Exception:
                        pass
                    print("CODE", code, flush=True)
                    return
            except Exception as e:
                print("poll err:", str(e)[:120], flush=True)
            time.sleep(6)
        with open(code_file, "w", encoding="utf-8") as f:
            json.dump({"code": None, "err": "timeout"}, f)
        print("TIMEOUT", flush=True)
    except Exception as e:
        with open(code_file, "w", encoding="utf-8") as f:
            json.dump({"code": None, "err": str(e)[:200]}, f)
        print("FATAL", str(e)[:200], flush=True)
        sys.exit(2)
    finally:
        sn.close()


def mode_accounts():
    state = os.path.join(os.environ["SECONDNO_HOME"], "state.json")
    try:
        accs = json.load(open(state, encoding="utf-8")).get("accounts", [])
    except Exception:
        accs = []
    for a in accs:
        print(json.dumps(a, ensure_ascii=False), flush=True)
    print(f"TOTAL {len(accs)}", flush=True)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    if args[0] == "reserve":
        mode_reserve(args[1:])
    elif args[0] == "accounts":
        mode_accounts()
    else:
        n = int(args[0])
        mode_register(n, gmail="--gmail" in args)


if __name__ == "__main__":
    main()
