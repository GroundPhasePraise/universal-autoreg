"""gh_http — GitHub HTTP-сессия (login+TOTP) и OAuth authorize (code).
Егресс: mobile bind (через newapi_lib handlers). Без браузера.
"""
import os
import sys, re, time, json, html as htmlmod, urllib.request, urllib.error, urllib.parse, http.cookiejar
import newapi_lib as L
import pyotp

UA = L.UA
GH = 'https://github.com'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def form_fields(fragment):
    """hidden/input поля формы."""
    out = {}
    for m in re.finditer(r'<input[^>]*>', fragment):
        tag = m.group(0)
        nm = re.search(r'name="([^"]+)"', tag)
        vl = re.search(r'value="([^"]*)"', tag)
        if nm:
            out[nm.group(1)] = htmlmod.unescape(vl.group(1)) if vl else ''
    return out


def find_form(html, action_hint):
    for m in re.finditer(r'<form[^>]*>.*?</form>', html, re.S):
        f = m.group(0)
        if action_hint in f:
            return f
    return None


class GHSession:
    def __init__(self, bind=True):
        self.jar = http.cookiejar.CookieJar()
        handlers = ([L._HSHandler(), L._HHandler()] if bind
                    else [urllib.request.HTTPSHandler(), urllib.request.HTTPHandler()])
        handlers += [NoRedirect, urllib.request.HTTPCookieProcessor(self.jar)]
        self.op = urllib.request.build_opener(*handlers)
        self.op.addheaders = [('User-Agent', UA),
                              ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'),
                              ('Accept-Language', 'en-US,en;q=0.9'),
                              ('Origin', GH), ('Referer', GH + '/')]
        self.detail = []

    def _req(self, url, data=None, timeout=30):
        r = urllib.request.Request(url, data=data)
        try:
            with self.op.open(r, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read().decode('utf-8', 'ignore')
        except Exception as e:
            return -1, {}, f'{type(e).__name__}: {str(e)[:120]}'

    def get(self, url):
        return self._req(url)

    def post_form(self, url, fields):
        return self._req(url, urllib.parse.urlencode(fields).encode())

    # ---- логин ----
    def login(self, login, password, totp):
        st, h, body = self.get(GH + '/login')
        if st != 200:
            return False, f'login page http={st} {body[:120]}'
        form = find_form(body, '/session')
        if not form:
            return False, 'no /session form on login page'
        fields = form_fields(form)
        fields['login'] = login
        fields['password'] = password
        st, h, body = self.post_form(GH + '/session', fields)
        self.detail.append(f'session http={st} loc={h.get("Location", "")[:80]}')
        loc = h.get('Location', '')
        # устройства/подтверждения
        if 'verified-device' in loc or 'device-verification' in loc or 'verify' in loc:
            return False, f'device-verification required: {loc}'
        if st in (301, 302) and ('two-factor' in loc or '2fa' in loc):
            return self._totp(totp, loc)
        if st in (301, 302) and loc.rstrip('/').endswith('github.com'):
            return self._check_login(login)
        # иногда 200 = страница ошибки/2fa
        if 'two-factor' in body or 'Two-factor' in body:
            return self._totp(totp, '/sessions/two-factor')
        return False, f'login unexpected http={st} loc={loc[:100]} body={body[:200]}'

    def _totp(self, totp, loc):
        page = loc if loc.startswith('http') else GH + loc
        st, h, body = self.get(page)
        for _ in range(3):  # редирект-цепочка до формы
            if st in (301, 302) and h.get('Location'):
                nloc = h['Location']
                page = nloc if nloc.startswith('http') else GH + nloc
                st, h, body = self.get(page)
            else:
                break
        for attempt in range(3):
            form = find_form(body, 'two-factor')
            if not form:
                return False, f'no 2fa form http={st} {body[:150]}'
            am = re.search(r'action="([^"]+)"', form)
            post_url = (am.group(1) if am else page)
            if not post_url.startswith('http'):
                post_url = GH + post_url
            fields = form_fields(form)
            code = pyotp.TOTP(totp).now()
            fields['app_otp'] = code
            st2, h2, body2 = self.post_form(post_url, fields)
            self.detail.append(f'2fa http={st2} loc={h2.get("Location", "")[:80]}')
            loc2 = h2.get('Location', '')
            if st2 in (301, 302):
                if 'two-factor' in loc2:
                    time.sleep(2)  # код протух — новый TOTP на след. попытке
                    st, h, body = self.get(page)
                    continue
                return self._check_login(loc2 or None)
            if 'Incorrect' in body2 or 'incorrect' in body2 or st2 == 422:
                time.sleep(2)
                st, h, body = self.get(page)
                continue
            return self._check_login(None)
        return False, 'totp: 3 неудачные попытки'

    def _check_login(self, redirect=None):
        if redirect:
            self.get(redirect if redirect.startswith('http') else GH + redirect)
        for c in self.jar:
            if c.name == 'logged_in' and c.value in ('yes', 'true'):
                return True, 'logged in (cookie)'
        st, h, body = self.get(GH + '/settings/profile')
        if st == 200 and ('authenticity' in body or 'Settings' in body):
            return True, 'logged in (settings)'
        st, h, body = self.get(GH + '/')
        if 'logged-in' in body or 'Sign out' in body or 'sign_out' in body:
            return True, 'logged in (home)'
        return False, f'not logged in: settings http={st}'

    # ---- OAuth authorize ----
    def oauth_code(self, client_id, state, scope='user:email'):
        url = (f'{GH}/login/oauth/authorize?client_id={urllib.parse.quote(client_id)}'
               f'&state={urllib.parse.quote(state)}&scope={urllib.parse.quote(scope)}')
        st, h, body = self.get(url)
        self.detail.append(f'authorize http={st} loc={h.get("Location", "")[:80]}')
        loc = h.get('Location', '')
        if st in (301, 302):
            code = self._code_from(loc)
            if code:
                return code, None
            if 'verified-device' in loc or 'device-verification' in loc:
                return None, f'device-verification: {loc}'
            return None, f'authorize redirect without code: {loc[:150]}'
        if st != 200:
            return None, f'authorize http={st} {body[:200]}'
        # consent-страница (или мета-редирект уже-авторизованного)
        open(os.path.join(os.environ.get('UA_LOGS', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')), '_consent.html'), 'w',
             encoding='utf-8').write(body)
        mref = re.search(r'url=([^"&]+)\?code=([a-f0-9]+)', body)
        if mref:
            return mref.group(2), None
        mc = re.search(r'[?&]code=([a-f0-9]{16,})', body)
        if mc:
            return mc.group(1), None
        tok = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', body)
        if not tok:
            tok = re.search(r'value="([^"]+)"[^>]*name="authenticity_token"', body)
        if not tok:
            tok = re.search(r'"authenticity_token"\s*:\s*"([^"]+)"', body)
        if not tok:
            return None, f'consent без authenticity_token (len={len(body)}): {body[:250]}'
        fields = {'authorize': '1', 'authenticity_token': tok.group(1),
                  'client_id': client_id, 'state': state, 'scope': scope,
                  'authorize': '1'}
        st2, h2, body2 = self.post_form(url, fields)
        self.detail.append(f'consent http={st2} loc={h2.get("Location", "")[:80]}')
        loc2 = h2.get('Location', '')
        if st2 in (301, 302):
            code = self._code_from(loc2)
            if code:
                return code, None
            return None, f'consent redirect без code: {loc2[:150]}'
        # 200: страница-редирект с code в meta-refresh
        mref = re.search(r'url=([^"&]+)\?code=([a-f0-9]+)', body2)
        if mref:
            return mref.group(2), None
        mc = re.search(r'[?&]code=([a-f0-9]{16,})', body2)
        if mc:
            return mc.group(1), None
        return None, f'consent http={st2} len={len(body2)}: {body2[:250]}'

    @staticmethod
    def _code_from(loc):
        if not loc:
            return None
        q = urllib.parse.urlparse(loc).query
        return urllib.parse.parse_qs(q).get('code', [None])[0]


def demo():
    accs = json.load(open(os.environ.get('UA_GH_ACCOUNTS', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'gh_accounts.json'))))
    a = accs[0]
    print('тест:', a['login'])
    s = GHSession(bind=True)
    ok, msg = s.login(a['login'], a['password'], a['totp'])
    print('login:', ok, msg)
    print('detail:', s.detail)
    if ok:
        code, err = s.oauth_code('Ov23li3WpJvZg1RmcPcl', 'test-state-doesnt-matter')
        print('code:', (code[:20] + '...') if code else None, '| err:', err)
        print('cookies:', sorted({c.name for c in s.jar}))


if __name__ == '__main__':
    demo()
