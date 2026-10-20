#!/usr/bin/env python3
"""UNIVERSAL AUTOREG DASHBOARD — единый пульт для 17+ авторег-провайдеров.

Stdlib-only (http.server), порт 8900. Запуск:  python dashboard.py
UI: http://127.0.0.1:8900

Возможности:
- Список провайдеров из providers.json (таргет, auth, капча, почта, прокси, награда)
- Запуск волн: POST /api/run {provider, count} → subprocess, лог в logs/<provider>.log
- Live-лог: GET /api/log?provider=X&offset=N
- Банк аккаунтов: GET /api/bank (статистика по провайдерам из data/bank.jsonl)
- Здоровье инфры: GET /api/health (captcha sidecar :8877, прокси-пул, почтовый пул, 2captcha баланс)
- Остановка волн: POST /api/stop {provider}
"""
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PORT = int(os.environ.get("UA_PORT", "8900"))
PYTHON = os.environ.get("UA_PYTHON", sys.executable)
LOGS = os.path.join(HERE, "logs")
os.makedirs(LOGS, exist_ok=True)
os.makedirs(os.path.join(HERE, "data"), exist_ok=True)

from lib import bank  # noqa: E402

RUNNING = {}  # provider -> {"proc": Popen, "started": ts, "count": N}
RUN_LOCK = threading.Lock()


def load_manifest():
    with open(os.path.join(HERE, "providers.json"), encoding="utf-8") as f:
        return json.load(f)


def valid_provider(name):
    """SECURITY: провайдер — только из манифеста, без path traversal."""
    import re as _re
    if not isinstance(name, str) or not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        return False
    return name in {p["id"] for p in load_manifest().get("providers", [])}


def infra_health():
    from lib import captcha, proxies
    h = {"sidecar": None, "proxies": {"total": 0}, "emails": {"pool": 0}, "twocaptcha": None}
    try:
        h["sidecar"] = captcha.sidecar_health()
    except Exception as e:
        h["sidecar"] = {"ok": False, "error": str(e)}
    try:
        h["proxies"]["total"] = len(proxies.load_pool())
    except Exception as e:
        h["proxies"]["error"] = str(e)
    mails = os.path.join(HERE, "data", "working_mails.txt")
    if os.path.exists(mails):
        h["emails"]["pool"] = sum(1 for _ in open(mails, encoding="utf-8"))
    try:
        h["twocaptcha"] = captcha.balance_2captcha()
    except Exception:
        pass
    return h


def run_wave(provider, count):
    if not valid_provider(provider):
        return {"error": f"unknown provider: {provider!r}"}
    with RUN_LOCK:
        if provider in RUNNING and RUNNING[provider]["proc"].poll() is None:
            return {"error": "already running", "pid": RUNNING[provider]["proc"].pid}
        script = os.path.join(HERE, "providers", provider + ".py")
        if not os.path.exists(script):
            return {"error": f"no such provider script: {script}"}
        logf = open(os.path.join(LOGS, provider + ".log"), "a", encoding="utf-8")
        logf.write(f"\n===== wave {count} started {time.strftime('%F %T')} =====\n")
        logf.flush()
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        proc = subprocess.Popen([PYTHON, script, str(count)], cwd=HERE,
                                stdout=logf, stderr=subprocess.STDOUT, env=env)
        logf.close()  # HANDLEFIX: child унаследовал dup — родительскую копию закрыть
        RUNNING[provider] = {"proc": proc, "started": time.time(), "count": count}
        return {"ok": True, "pid": proc.pid}


HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>UNIVERSAL AUTOREG</title><style>
body{background:#0d0f12;color:#d7dae0;font:14px/1.5 Consolas,monospace;margin:0;padding:18px}
h1{color:#ff6b35;font-size:20px;margin:0 0 4px}
.sub{color:#7a8290;margin-bottom:16px}
.hbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}
.hcard{background:#151920;border:1px solid #232a35;border-radius:8px;padding:10px 14px;min-width:150px}
.hcard b{color:#ff6b35;font-size:18px;display:block}
table{border-collapse:collapse;width:100%;margin-bottom:20px}
th{color:#7a8290;text-align:left;padding:6px 8px;border-bottom:1px solid #232a35;font-size:12px}
td{padding:7px 8px;border-bottom:1px solid #1a2029;vertical-align:top;font-size:12.5px}
tr:hover td{background:#131820}
.id{color:#ff6b35;font-weight:bold;white-space:nowrap}
.tag{background:#1c2530;border-radius:4px;padding:1px 6px;color:#8fb7d9;white-space:nowrap;font-size:11px}
.tag.free{background:#14261a;color:#6fcf7f}
.tag.paid{background:#2a1c14;color:#d9a05b}
.tag.none{background:#1c2530;color:#5a6472}
button{background:#ff6b35;border:0;color:#0d0f12;font-weight:bold;padding:4px 10px;border-radius:5px;cursor:pointer;font-family:inherit}
button.stop{background:#3a2028;color:#ff8b8b}
button:disabled{background:#232a35;color:#5a6472;cursor:default}
input[type=number]{width:52px;background:#0d0f12;border:1px solid #232a35;color:#d7dae0;padding:3px;border-radius:4px;font-family:inherit}
pre.log{background:#0a0c0f;border:1px solid #232a35;border-radius:8px;padding:12px;height:280px;overflow-y:auto;font-size:12px;white-space:pre-wrap;display:none}
.notes{color:#5a6472;font-size:11.5px}
a{color:#8fb7d9}
.foot{color:#3d4654;margin-top:24px;font-size:12px}
</style></head><body>
<h1>&#129685; UNIVERSAL AUTOREG DASHBOARD</h1>
<div class="sub">17+ провайдеров &middot; локальная капча &middot; почтовые пулы &middot; прокси-ротация &middot; банк аккаунтов</div>
<div class="hbar" id="health"></div>
<div id="prov"></div>
<pre class="log" id="logbox"></pre>
<div class="foot">&#128123; <a href="https://t.me/AlStack">иишко</a> &middot; universal-autoreg &middot; секретов нет: config.json (gitignored)</div>
<script>
let curLog=null,logOff=0,timer=null;
function tag(t){const f=/free|none/i.test(t)?'free':/2captcha|paid/i.test(t)?'paid':'';return `<span class="tag ${f}">${t}</span>`}
async function render(){
 const m=await (await fetch('/api/manifest')).json();
 const b=await (await fetch('/api/bank')).json();
 const h=await (await fetch('/api/health')).json();
 document.getElementById('health').innerHTML=`
  <div class="hcard"><b>${h.sidecar&&h.sidecar.ok?'UP':'DOWN'}</b>captcha sidecar :8877</div>
  <div class="hcard"><b>${h.proxies.total}</b>прокси в пуле</div>
  <div class="hcard"><b>${h.emails.pool}</b>t-online ящиков</div>
  <div class="hcard"><b>${h.twocaptcha&&h.twocaptcha.status==1?'$'+h.twocaptcha.request:'—'}</b>2captcha баланс</div>
  <div class="hcard"><b>${Object.values(b).reduce((s,v)=>s+v.total,0)}</b>аккаунтов в банке</div>`;
 let rows='';
 for(const p of m.providers){
  const st=(b[p.id]||{total:0,with_token:0});
  const run=p.running?`<button class="stop" onclick="stop('${p.id}')">STOP ${p.pid}</button>`:
   `<input type="number" id="n_${p.id}" value="5" min="1" max="500"> <button onclick="run('${p.id}')">RUN</button>`;
  rows+=`<tr><td class="id">${p.id}${p.running?' &#9654;':''}</td>
   <td>${p.target}</td><td>${tag(p.auth)}</td><td>${tag(p.captcha)}</td>
   <td>${p.reward}</td><td style="text-align:right"><b>${st.total}</b><br><span class="notes">${st.with_token} с токеном</span></td>
   <td>${run} <button onclick="showLog('${p.id}')">LOG</button><br><span class="notes">${p.notes||''}</span></td></tr>`;
 }
 document.getElementById('prov').innerHTML=`<table><tr><th>provider</th><th>таргет</th><th>auth</th><th>капча</th><th>награда</th><th>банк</th><th>запуск</th></tr>${rows}</table>`;
}
async function run(id){const n=document.getElementById('n_'+id).value;
 const r=await (await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:id,count:+n})})).json();
 if(r.error)alert(r.error);showLog(id);render();}
async function stop(id){await fetch('/api/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:id})});render();}
function showLog(id){curLog=id;logOff=0;const lb=document.getElementById('logbox');lb.style.display='block';lb.textContent='';
 if(timer)clearInterval(timer);timer=setInterval(pullLog,2000);pullLog();}
async function pullLog(){if(!curLog)return;
 const r=await (await fetch(`/api/log?provider=${curLog}&offset=${logOff}`)).json();
 if(r.text){const lb=document.getElementById('logbox');lb.textContent+=r.text;logOff=r.offset;lb.scrollTop=lb.scrollHeight;}}
render();setInterval(render,10000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, HTML, "text/html")
        if u.path == "/api/manifest":
            m = load_manifest()
            with RUN_LOCK:
                for p in m["providers"]:
                    r = RUNNING.get(p["id"])
                    p["running"] = bool(r and r["proc"].poll() is None)
                    p["pid"] = r["proc"].pid if p["running"] else None
            return self._send(200, m)
        if u.path == "/api/bank":
            return self._send(200, bank.stats())
        if u.path == "/api/health":
            return self._send(200, infra_health())
        if u.path == "/api/log":
            q = parse_qs(u.query)
            prov = q.get("provider", [""])[0]
            # SECURITY: только валидное имя провайдера — иначе path traversal (../../../etc)
            import re as _re
            if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", prov or ""):
                return self._send(400, {"error": "bad provider"})
            off = int(q.get("offset", ["0"])[0])
            path = os.path.join(LOGS, prov + ".log")
            if not os.path.exists(path):
                return self._send(200, {"text": "", "offset": off})
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(off)
                text = f.read(64 * 1024)
                newoff = f.tell()
            return self._send(200, {"text": text, "offset": newoff})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/run":
            b = self._body()
            return self._send(200, run_wave(b.get("provider", ""), int(b.get("count", 1))))
        if u.path == "/api/stop":
            b = self._body()
            with RUN_LOCK:
                r = RUNNING.get(b.get("provider", ""))
                if r and r["proc"].poll() is None:
                    pid = r["proc"].pid
                    if os.name == "nt":
                        # TREEFIX: terminate() убивает только python-обёртку —
                        # дети (camoufox/chrome) выживают сиротами. Убивать всю process tree.
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                       capture_output=True)
                    else:
                        r["proc"].terminate()
                    return self._send(200, {"ok": True, "terminated": pid})
            return self._send(200, {"ok": False})
        return self._send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"UNIVERSAL AUTOREG DASHBOARD: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
