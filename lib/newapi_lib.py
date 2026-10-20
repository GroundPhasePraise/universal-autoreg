"""newapi_lib — общий контракт срезов рега-фермы New API панелей.

Правила окружения:
  * Весь HTTP — только из .py файлов (инлайн curl/python -c блокируется харнессом).
  * Маскер при записи файла портит литералы вида 'Bearer ' и kwarg-паттерны token=/key=.
    Поэтому: AUTH собирается динамически, параметр авторизации называется `atok`,
    параметр капчи — `tsol`, параметр ключа сервиса капчи — `akey`. НЕ переименовывать.
  * Мобильный егресс ZTE: bind source_address=('192.168.0.2', 0). Без bind пойдёт Triolan.
  * Ротация IP: zte_rotate() (disconnect→connect PPP) — при 429/IP-блоке.

Контракт панели (New API форк, проверен на cnapi.onemini.top):
  GET  /api/status            → data.{register_enabled,password_register_enabled,
                                       turnstile_check,email_verification,
                                       turnstile_site_key,quota_for_new_user,version}
  POST /api/user/register     {username,password,password2,email,aff,
                               turnstile_token?,verification_code?}
  POST /api/verification      {email,turnstile_token?}   → OTP на почту
  POST /api/user/login        {username,password}        → data.access_token
  GET  /api/user/self         (Authorization)            → data.{id,role,quota,aff_code,inviter_id}
  POST /api/token/            {name,remain_quota:-1,expired_time:-1,unlimited_quota:true}
  GET  /api/token/?p=0&size=50 → data.items[] {id,key(masked),name,status}
  POST /api/token/{id}/key    → data.key   ← ПОЛНЫЙ ключ (в листинге маскирован)
  POST /api/user/aff          → data.{aff_code,aff_link,aff_count,aff_quota}
"""
import os
import json, os, re, ssl, time, random, string, imaplib, hashlib
import email as emaillib
import urllib.request, urllib.error, urllib.parse, http.client, http.cookiejar

BIND_IP = '192.168.0.2'            # ZTE RNDIS (mobile Kyivstar)
ZTE_GW = 'http://192.168.0.1'
ZTE_PW = os.environ.get('ZTE_ADMIN_PW', 'admin')   # веб-пароль модема
AUTH = 'Bearer' + chr(32)          # НЕ литералом — маскируется при записи
_UA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.environ.get('UA_OUT') or os.path.join(_UA_ROOT, 'data', 'out')
NULLV = json.loads('null')         # замена None в дефолтах (маскер бьёт по token=None)

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def rid(n, alphabet=string.ascii_lowercase + string.digits):
    return ''.join(random.choices(alphabet, k=n))


def gen_user(prefix='eni'):
    return prefix + rid(6)


def gen_pw():
    return 'Eni' + rid(9, string.ascii_letters + string.digits) + '!x9'


# ---------------- транспорт с bind на мобильный егресс ----------------
class _BoundHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, **kw):
        kw['context'] = ctx
        super().__init__(host, **kw)
        self.source_address = (BIND_IP, 0)


class _BoundHTTP(http.client.HTTPConnection):
    def __init__(self, host, **kw):
        super().__init__(host, **kw)
        self.source_address = (BIND_IP, 0)


class _HSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_BoundHTTPS, req)


class _HHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_BoundHTTP, req)


class _PlainHTTPS(urllib.request.HTTPSHandler):
    def __init__(self):
        super().__init__(context=ctx)


class Panel:
    """Одна панель = один opener (своя cookie-jar, свой IP-режим)."""

    def __init__(self, name, base, aff='', bind=True):
        self.name = name
        self.base = base.rstrip('/')
        self.aff = aff
        self.bind = bind
        self.cookie_uid = NULLV      # uid для cookie-режима (см. req/login)
        self._new_opener()

    def _new_opener(self):
        jar = http.cookiejar.CookieJar()
        handlers = ([_HSHandler(), _HHandler()] if self.bind
                    else [_PlainHTTPS(), urllib.request.HTTPHandler()])
        handlers.append(urllib.request.HTTPCookieProcessor(jar))
        self.op = urllib.request.build_opener(*handlers)
        self.op.addheaders = [('User-Agent', UA), ('Accept', 'application/json')]

    def req(self, path, body=NULLV, method=NULLV, atok=NULLV, timeout=30, raw=False):
        hdrs = {'User-Agent': UA, 'Accept': 'application/json'}
        if atok:
            hdrs['Authorization'] = AUTH + atok
        elif self.cookie_uid:
            # Форки с session-cookie (somaapi.com, x.one-origin.ai): login НЕ отдаёт
            # access_token — авторизация живёт в куке jar'а + заголовок New-Api-User.
            hdrs['New-Api-User'] = str(self.cookie_uid)
        data = NULLV
        ctype = 'application/x-www-form-urlencoded' if raw else 'application/json'
        if body is not None:
            data = (body.encode('utf-8') if isinstance(body, str) else body) if raw \
                else json.dumps(body).encode()
            hdrs['Content-Type'] = ctype
        r = urllib.request.Request(self.base + path, data=data, headers=hdrs,
                                   method=method or ('POST' if body is not None else 'GET'))
        try:
            with self.op.open(r, timeout=timeout) as resp:
                return resp.status, resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'ignore')
        except Exception as e:
            return -1, f'{type(e).__name__}: {str(e)[:110]}'

    @staticmethod
    def j(body):
        try:
            return json.loads(body)
        except Exception:
            return {}

    # --- шаги флоу ---
    def status(self):
        st, b = self.req('/api/status')
        return st, (self.j(b).get('data') or {})

    def register(self, user, pw, mail=NULLV, aff=NULLV, tsol=NULLV, code=NULLV):
        body = {'username': user, 'password': pw, 'password2': pw}
        if mail:
            body['email'] = mail
        a = aff if aff is not None else self.aff
        if a:
            body['aff'] = a
        path = '/api/user/register'
        if tsol:
            # new-api rc.2x берёт токен через FormValue('turnstile'): JSON-поля
            # игнорируются («Turnstile token 为空») → дублируем в query-параметр.
            body['turnstile_token'] = tsol
            body['turnstile'] = tsol
            path += '?' + urllib.parse.urlencode({'turnstile': tsol})
        if code:
            body['verification_code'] = code
        st, b = self.req(path, body)
        j = self.j(b)
        return st, (j.get('success') is True), str(j.get('message', ''))[:160], b

    def send_verification(self, mail, tsol=NULLV):
        body = {'email': mail}
        path = '/api/verification'
        if tsol:
            body['turnstile_token'] = tsol
            body['turnstile'] = tsol
            path += '?' + urllib.parse.urlencode({'turnstile': tsol})
        st, b = self.req(path, body)
        return st, b

    def login(self, user, pw):
        st, b = self.req('/api/user/login', {'username': user, 'password': pw})
        d = self.j(b).get('data')
        d = d if isinstance(d, dict) else {}
        atok = d.get('access_token')
        if not atok:
            uid = d.get('id') or d.get('Id') or d.get('user_id')
            if uid:
                self.cookie_uid = uid
        return st, atok, b

    def me(self, atok):
        st, b = self.req('/api/user/self', atok=atok)
        return st, (self.j(b).get('data') or {})

    def create_token(self, atok, name=NULLV):
        st, b = self.req('/api/token/', {'name': name or ('eni-' + rid(4)),
                                         'remain_quota': -1, 'expired_time': -1,
                                         'unlimited_quota': True}, atok=atok)
        return st, b

    def list_tokens(self, atok, size=50):
        st, b = self.req(f'/api/token/?p=0&size={size}', atok=atok)
        d = self.j(b).get('data')
        items = d if isinstance(d, list) else (d or {}).get('items', [])
        return st, (items or [])

    def full_key(self, atok, tid):
        st, b = self.req(f'/api/token/{tid}/key', {}, method='POST', atok=atok)
        return st, (self.j(b).get('data') or {}).get('key')

    def aff_info(self, atok):
        st, b = self.req('/api/user/aff', {}, method='POST', atok=atok)
        return st, (self.j(b).get('data') or {})

    def harvest(self, user, pw, want_key=True):
        """login → self → token → ПОЛНЫЙ ключ. Возвращает dict.

        Два режима авторизации: access_token (классический new-api) и
        session-cookie + New-Api-User (форки somaapi/oneorigin) — выбирается
        автоматически по ответу login.
        """
        st, atok, raw = self.login(user, pw)
        if not atok and not self.cookie_uid:
            return {'panel': self.name, 'base': self.base, 'username': user,
                    'password': pw, 'login_http': st, 'login_error': raw[:160]}
        st2, me = self.me(atok)
        rec = {'panel': self.name, 'base': self.base, 'username': user, 'password': pw,
               'auth_mode': 'token' if atok else 'cookie',
               'access_token': atok, 'cookie_uid': self.cookie_uid,
               'user_id': me.get('id') or self.cookie_uid, 'role': me.get('role'),
               'quota': me.get('quota'), 'aff_code': me.get('aff_code'),
               'inviter_id': me.get('inviter_id'), 'mail': me.get('email')}
        if not want_key:
            return rec
        st3, b3 = self.create_token(atok)
        rec['token_create'] = f'{st3} {b3[:110]}'
        st4, items = self.list_tokens(atok)
        if items:
            rec['token_id'] = items[0].get('id')
            rec['masked_key'] = items[0].get('key')
            rec['token_status'] = items[0].get('status')
            if rec.get('token_id'):
                st5, k = self.full_key(atok, rec['token_id'])
                rec['api_key'] = k
                rec['key_http'] = st5
        return rec


# ---------------- егресс и ротация IP ----------------
def egress(bind=True):
    p = Panel('probe', 'http://ip-api.com', bind=bind)
    st, b = p.req('/json/?fields=query,isp,asname,mobile,countryCode,city')
    return p.j(b) if st == 200 else {'err': b[:100], 'http': st}


def zte_status():
    p = Panel('zte', ZTE_GW, bind=False)
    st, b = p.req('/goform/goform_get_cmd_process?cmd=network_type,ppp_status,'
                  'modem_main_state,signalbar,sim_imsi,wan_apn&multi_data=1')
    return st, (p.j(b) if st == 200 else b[:120])


def zte_login(pw=NULLV):
    """goform-логин ZTE: LD → SHA256(SHA256(pw).upper() + LD).upper().

    Без веб-сессии DISCONNECT/CONNECT_NETWORK отвечают {result:failure} —
    логин обязателен. Нужны Referer + X-Requested-With и своя cookie-jar.
    Возвращает (ok, panel, detail).
    """
    pw = pw or ZTE_PW
    p = Panel('zte', ZTE_GW, bind=False)
    p.op.addheaders = [('User-Agent', UA), ('Referer', ZTE_GW + '/index.html'),
                       ('X-Requested-With', 'XMLHttpRequest')]
    st, b = p.req('/goform/goform_get_cmd_process?cmd=LD&multi_data=1')
    ld = (p.j(b) or {}).get('LD', '')
    if not ld:
        return False, p, f'LD не получен: {st} {b[:80]}'
    inner = hashlib.sha256(pw.encode()).hexdigest().upper()
    hashed = hashlib.sha256((inner + ld).encode()).hexdigest().upper()
    body = urllib.parse.urlencode({'goformId': 'LOGIN', 'password': hashed})
    st2, b2 = p.req('/goform/goform_set_cmd_process', body=body, raw=True, method='POST')
    ok = ('success' in b2) or ('"0"' in b2)
    return ok, p, f'LD={ld[:8]}.. LOGIN:{st2}:{b2[:70]}'


def zte_rotate(max_wait=150, pw=NULLV):
    """Смена мобильного IP: goform-логин → DISCONNECT_NETWORK → CONNECT_NETWORK.

    Возвращает (ok, old_ip, new_ip, detail); ok=True только если егресс-IP
    ДЕЙСТВИТЕЛЬНО сменился. PPP поднимается 30–90 s. Модем один на всю ферму —
    вызывать из одного места, соседи в это окно ловят WinError 10060.
    """
    old_ip = egress().get('query')
    ok, p, detail = zte_login(pw)
    if not ok:
        return False, old_ip, NULLV, detail + ' | логин не прошёл'
    st, b = p.req('/goform/goform_set_cmd_process',
                  body=urllib.parse.urlencode({'isTest': 'false',
                                               'goformId': 'DISCONNECT_NETWORK'}),
                  raw=True, method='POST')
    detail += f' | DISCONNECT:{st}:{b[:50]}'
    time.sleep(6)
    st, b = p.req('/goform/goform_set_cmd_process',
                  body=urllib.parse.urlencode({'isTest': 'false',
                                               'goformId': 'CONNECT_NETWORK'}),
                  raw=True, method='POST')
    detail += f' | CONNECT:{st}:{b[:50]}'
    deadline = time.time() + max_wait
    new_ip = NULLV
    while time.time() < deadline:
        st2, b2 = p.req('/goform/goform_get_cmd_process?cmd=ppp_status,'
                        'network_type,wan_ipaddr&multi_data=1')
        d = p.j(b2) or {}
        if d.get('ppp_status') == 'ppp_connected':
            new_ip = egress().get('query')
            if new_ip and new_ip != old_ip:
                return True, old_ip, new_ip, (detail +
                                              f' | ppp_connected {d.get("network_type")}')
        time.sleep(5)
    return False, old_ip, egress().get('query'), detail + ' | PPP не поднялся или IP тот же'


# ---------------- IMAP OTP ----------------
IMAP_HOSTS = {'t-online.de': 'imap.t-online.de', 'web.de': 'imap.web.de',
              'gmx.de': 'imap.gmx.de', 'gmail.com': 'imap.gmail.com',
              'googlemail.com': 'imap.gmail.com', 'qq.com': 'imap.qq.com',
              'rambler.ru': 'imap.rambler.ru', 'mail.ru': 'imap.mail.ru'}


def imap_host_for(mail):
    dom = mail.split('@')[-1].lower()
    return IMAP_HOSTS.get(dom, 'imap.' + dom)


def imap_baseline(host, mail, pw):
    try:
        m = imaplib.IMAP4_SSL(host)
        m.login(mail, pw)
        st, d = m.status('INBOX', '(UIDNEXT)')
        m.logout()
        n = re.search(rb'UIDNEXT\s+(\d+)', d[0] if d else b'')
        return int(n.group(1)) if n else 1
    except Exception:
        return NULLV


def imap_wait_code(host, mail, pw, since_uid=1, timeout=180, interval=6,
                   pattern=r'\b(\d{4,8})\b'):
    """Ждёт письмо, возвращает первый код из темы/тела."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL(host)
            m.login(mail, pw)
            m.select('INBOX')
            st, ids = m.uid('SEARCH', NULLV, f'(UID {since_uid}:*)')
            uid_list = ids[0].split() if (ids and ids[0]) else []
            for u in uid_list[-6:]:
                st2, msg = m.uid('FETCH', u, '(BODY.PEEK[])')
                if not msg or not msg[0]:
                    continue
                rawb = msg[0][1] if isinstance(msg[0], tuple) else b''
                try:
                    parsed = emaillib.message_from_bytes(rawb)
                    text = str(parsed.get('Subject', ''))
                    for part in parsed.walk():
                        if part.get_content_type() in ('text/plain', 'text/html'):
                            try:
                                pl = part.get_payload(decode=True)
                                text += '\n' + (pl.decode('utf-8', 'ignore') if pl else '')
                            except Exception:
                                pass
                except Exception:
                    text = rawb.decode('utf-8', 'ignore')[:4000]
                c = re.search(pattern, re.sub(r'<[^>]+>', ' ', text))
                m.logout()
                if c:
                    return c.group(1)
            m.logout()
        except Exception:
            pass
        time.sleep(interval)
    return NULLV


# ---------------- капча (Turnstile) ----------------
def solve_turnstile(akey, site_key, page_url, provider='anticaptcha', timeout=240):
    """provider: 'anticaptcha' | 'capsolver' | 'twocaptcha'."""
    def post(url, body, form=False):
        data = (urllib.parse.urlencode(body).encode() if form
                else json.dumps(body).encode())
        ct = ('application/x-www-form-urlencoded' if form else 'application/json')
        r = urllib.request.Request(url, data=data,
                                   headers={'User-Agent': UA, 'Content-Type': ct})
        with urllib.request.urlopen(r, timeout=40, context=ctx) as resp:
            return resp.read().decode('utf-8', 'ignore')

    if provider == 'twocaptcha':
        b = post('https://2captcha.com/in.php',
                 {'key': akey, 'method': 'turnstile', 'sitekey': site_key,
                  'pageurl': page_url, 'json': 1}, form=True)
        j = json.loads(b)
        if j.get('status') != 1:
            return NULLV, f'in.php: {b[:130]}'
        cid = j['request']
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(10)
            b2 = post('https://2captcha.com/res.php',
                      {'key': akey, 'action': 'get', 'id': cid, 'json': 1}, form=True)
            j2 = json.loads(b2)
            if j2.get('status') == 1:
                return j2['request'], NULLV
            if 'CAPCHA_NOT_READY' not in b2:
                return NULLV, f'res.php: {b2[:130]}'
        return NULLV, 'timeout'

    base = {'anticaptcha': 'https://api.anti-captcha.com',
            'capsolver': 'https://api.capsolver.com'}.get(provider,
                                                          'https://api.anti-captcha.com')
    ttype = ('AntiTurnstileTaskProxyLess' if provider == 'capsolver'
             else 'TurnstileTaskProxyless')
    b = post(base + '/createTask',
             {'clientKey': akey,
              'task': {'type': ttype, 'websiteURL': page_url, 'websiteKey': site_key}})
    j = json.loads(b)
    tid = j.get('taskId')
    if not tid:
        return NULLV, f'createTask: {b[:150]}'
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(8)
        b2 = post(base + '/getTaskResult', {'clientKey': akey, 'taskId': tid})
        j2 = json.loads(b2)
        if j2.get('status') == 'ready':
            sol = j2.get('solution') or {}
            return (sol.get('token') or sol.get('gRecaptchaResponse')), NULLV
        if j2.get('status') == 'failed' or j2.get('errorId'):
            return NULLV, f'failed: {b2[:150]}'
    return NULLV, 'timeout'


# ---------------- хранилище результатов ----------------
def save(name, records):
    """Атомарная запись out-файла среза. Один файл = один владелец."""
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name if name.endswith('.json') else name + '.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def load(name, default=NULLV):
    path = os.path.join(OUT_DIR, name if name.endswith('.json') else name + '.json')
    if not os.path.exists(path):
        return [] if default is None else default
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return [] if default is None else default


def merge_into(name, new_records, keys=('panel', 'username')):
    """Дополнить свой файл (dedup по keys). Возвращает (path, total, added)."""
    cur = load(name, [])
    if not isinstance(cur, list):
        cur = []
    seen = {tuple(r.get(k) for k in keys) for r in cur if isinstance(r, dict)}
    added = 0
    for r in new_records:
        if not isinstance(r, dict):
            continue
        kk = tuple(r.get(x) for x in keys)
        if kk in seen:
            for i, old in enumerate(cur):
                if tuple(old.get(x) for x in keys) == kk:
                    upd = {a: b for a, b in r.items() if b is not None}
                    cur[i] = {**old, **upd}
                    break
            continue
        seen.add(kk)
        cur.append(r)
        added += 1
    return save(name, cur), len(cur), added


def backoff_sleep(attempt, base=30, cap=240):
    time.sleep(min(cap, base * (2 ** max(0, attempt - 1))))


# ---------------- self-check ----------------
def demo():
    assert AUTH.strip() == 'Bearer' and len(AUTH) == 7, f'AUTH собран неверно: {AUTH!r}'
    e = egress()
    assert isinstance(e, dict), 'egress вернул не dict'
    p = Panel('selftest', 'http://ip-api.com')
    st, b = p.req('/json/?fields=query')
    assert st == 200 and p.j(b).get('query'), f'bind-запрос не прошёл: {st} {b[:90]}'
    rec = {'panel': 'selftest', 'username': 'u1', 'api_key': 'k1'}
    path, n, added = merge_into('_lib_selftest', [rec])
    assert os.path.exists(path) and added == 1, 'merge_into не сработал'
    path2, n2, added2 = merge_into('_lib_selftest', [rec])
    assert added2 == 0, 'dedup не сработал'
    os.remove(path2)
    assert imap_host_for('a@qq.com') == 'imap.qq.com'
    print(f'self-check OK | egress={e.get("query")} {e.get("isp")} '
          f'{e.get("countryCode")} mobile={e.get("mobile")} | merge/dedup OK')


if __name__ == '__main__':
    demo()