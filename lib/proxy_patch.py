# proxy_patch.py — инъекция свежих прокси (пул ProxyGrabReform_bot) во все HTTP-сессии
import json, os, random, itertools, urllib.request, ssl

_PP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY_DB = os.environ.get('UA_PROXY_DB') or os.path.join(_PP_ROOT, 'data', 'proxies.db')

def _load_live():
    """Живые прокси из бот-пула, ротация round-robin."""
    import sqlite3
    if not os.path.exists(PROXY_DB):
        return []
    con = sqlite3.connect(PROXY_DB)
    rows = [r[0] for r in con.execute("select proxy from pool where alive=1").fetchall()]
    con.close()
    # свежий live-список优先 (прозвон 5 мин назад), фолбэк — весь пул
    try:
        live = json.load(open(os.path.join(_PP_ROOT, 'data', '_live_proxies.json'), encoding='utf-8'))
        rows = [x[0] for x in live] + [r for r in rows if r not in {x[0] for x in live}]
    except Exception:
        pass
    return rows

PROXIES = _load_live()
_cyc = itertools.cycle(PROXIES) if PROXIES else None

def next_proxy():
    return next(_cyc) if _cyc else None

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

def _proxied_opener(cookies=True, proxy=None):
    p = proxy or next_proxy()
    handlers = [urllib.request.ProxyHandler({'http': p, 'https': p}) if p else urllib.request.NoHandler()]
    handlers = [h for h in handlers if not isinstance(h, urllib.request.NoHandler)]
    handlers.append(urllib.request.HTTPSHandler(context=_ctx))
    if cookies:
        handlers.append(urllib.request.HTTPCookieProcessor())
    return urllib.request.build_opener(*handlers)

def apply():
    """Монкейпатчит GHSession и Panel из regfarm — каждая новая сессия получает свой прокси."""
    import sys
    import newapi_lib as L
    import gh_http

    # --- Panel: НАПРЯМУЮ (прокси-IP банятся панелью 403) ---
    _orig_init = L.Panel.__init__
    def panel_init(self, name, base, aff='', bind=True, **kw):
        self.name = name
        self.base = base.rstrip('/')
        self.aff = aff
        self.bind = False
        self.cookie_uid = L.NULLV
        self.proxy = None
        import http.cookiejar
        self._jar = http.cookiejar.CookieJar()
        hs = [urllib.request.HTTPSHandler(context=_ctx), urllib.request.HTTPHandler(),
              urllib.request.HTTPCookieProcessor(self._jar)]
        self.op = urllib.request.build_opener(*hs)
        self.op.addheaders = [('User-Agent', L.UA), ('Accept', 'application/json')]
    L.Panel.__init__ = panel_init

    # --- GHSession: только ЖИВЫЕ для GitHub прокси + авто-прокрутка при таймауте ---
    live = []
    try:
        live = [x for x in json.load(open(os.path.join(_PP_ROOT, 'data', '_gh_proxies.json'), encoding='utf-8'))]
    except Exception:
        pass
    _lcyc = itertools.cycle(live) if live else None
    _orig_gh = gh_http.GHSession.__init__
    def gh_init(self, bind=True, **kw):
        import http.cookiejar
        self.jar = http.cookiejar.CookieJar()
        self.proxy = next(_lcyc) if _lcyc else None
        hs = [urllib.request.ProxyHandler({'http': self.proxy, 'https': self.proxy})] if self.proxy else []
        hs += [urllib.request.HTTPSHandler(context=_ctx), urllib.request.HTTPHandler(),
               gh_http.NoRedirect, urllib.request.HTTPCookieProcessor(self.jar)]
        self.op = urllib.request.build_opener(*hs)
        self.op.addheaders = [('User-Agent', gh_http.UA),
                              ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'),
                              ('Accept-Language', 'en-US,en;q=0.9'),
                              ('Origin', gh_http.GH), ('Referer', gh_http.GH + '/')]
        self.detail = []

        # авто-ротация прокси при сетевых ошибках (-1)
        _orig_req = gh_http.GHSession._req
        def _req_retry(self, url, data=None, timeout=30, _tries=3):
            last = None
            for i in range(_tries):
                st, h, body = _orig_req(self, url, data, timeout)
                if st != -1:
                    return st, h, body
                last = (st, h, body)
                # таймаут/conn error → новый прокси и пересобрать opener
                np = next(_lcyc) if _lcyc else None
                self.proxy = np
                hs = [urllib.request.ProxyHandler({'http': np, 'https': np})] if np else []
                hs += [urllib.request.HTTPSHandler(context=_ctx), urllib.request.HTTPHandler(),
                       gh_http.NoRedirect, urllib.request.HTTPCookieProcessor(self.jar)]
                self.op = urllib.request.build_opener(*hs)
                self.op.addheaders = [('User-Agent', gh_http.UA),
                                      ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'),
                                      ('Accept-Language', 'en-US,en;q=0.9'),
                                      ('Origin', gh_http.GH), ('Referer', gh_http.GH + '/')]
            return last
        self._req = lambda url, data=None, timeout=30: _req_retry(self, url, data, timeout)
    gh_http.GHSession.__init__ = gh_init
    return len(PROXIES)

if __name__ == '__main__':
    n = apply()
    print('proxy pool:', n)
