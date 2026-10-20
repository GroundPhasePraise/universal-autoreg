"""gh_session — GitHub HTTP-сессия (login + TOTP) и OAuth authorize (code).
Standalone: только stdlib + pyotp. Без браузера.
"""
import re
import time
import html as htmlmod
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar

import pyotp

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
GH = 'https://github.com'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def form_fields(fragment):
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
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPSHandler(), urllib.request.HTTPHandler(),
                    NoRedirect, urllib.request.HTTPCookieProcessor(self.jar)]
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

    # ---- login ----
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
        if 'verified-device' in loc or 'device-verification' in loc or 'verify' in loc:
            return False, f'device-verification required: {loc}'
        if st in (301, 302) and ('two-factor' in loc or '2fa' in loc):
            return self._totp(totp, loc)
        if st in (301, 302) and loc.rstrip('/').endswith('github.com'):
            return self._check_login(login)
        if 'two-factor' in body or 'Two-factor' in body:
            return self._totp(totp, '/sessions/two-factor')
        return False, f'login unexpected http={st} loc={loc[:100]} body={body[:200]}'

    def _totp(self, totp, loc):
        page = loc if loc.startswith('http') else GH + loc
        st, h, body = self.get(page)
        for _ in range(3):
            if st in (301, 302) and h.get('Location'):
                nloc = h['Location']
                page = nloc if nloc.startswith('http') else GH + nloc
                st, h, body = self.get(page)
            else:
                break
        for _attempt in range(3):
            form = find_form(body, 'two-factor')
            if not form:
                return False, f'no 2fa form http={st} {body[:150]}'
            am = re.search(r'action="([^"]+)"', form)
            post_url = (am.group(1) if am else page)
            if not post_url.startswith('http'):
                post_url = GH + post_url
            fields = form_fields(form)
            fields['app_otp'] = pyotp.TOTP(totp).now()
            st2, h2, body2 = self.post_form(post_url, fields)
            self.detail.append(f'2fa http={st2} loc={h2.get("Location", "")[:80]}')
            loc2 = h2.get('Location', '')
            if st2 in (301, 302):
                if 'two-factor' in loc2:
                    time.sleep(2)
                    st, h, body = self.get(page)
                    continue
                return self._check_login(loc2 or None)
            if 'Incorrect' in body2 or 'incorrect' in body2 or st2 == 422:
                time.sleep(2)
                st, h, body = self.get(page)
                continue
            return self._check_login(None)
        return False, 'totp: 3 failed attempts'

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
    def oauth_code(self, client_id, state, scope='user:email', redirect_uri=None):
        url = (f'{GH}/login/oauth/authorize?client_id={urllib.parse.quote(client_id)}'
               f'&state={urllib.parse.quote(state)}&scope={urllib.parse.quote(scope)}')
        if redirect_uri:
            url += f'&redirect_uri={urllib.parse.quote(redirect_uri, safe="")}'
            url += '&response_type=code'
        st, h, body = self.get(url)
        self.detail.append(f'authorize http={st} loc={h.get("Location", "")[:80]}')
        loc = h.get('Location', '')
        if st in (301, 302):
            code = self._code_from(loc)
            if code:
                return code, state, None
            if 'verified-device' in loc or 'device-verification' in loc:
                return None, state, f'device-verification: {loc}'
            return None, state, f'authorize redirect without code: {loc[:150]}'
        if st != 200:
            return None, state, f'authorize http={st} {body[:200]}'
        # meta-refresh page ("OAuth application authorized") — code+state inside body
        m = re.search(r'oauth/github\?code=([a-f0-9]{16,})[^"\']*state=([A-Za-z0-9_\-]+)', body)
        if m:
            return m.group(1), m.group(2), None
        mref = re.search(r'url=([^"&]+)\?code=([a-f0-9]+)', body)
        if mref:
            return mref.group(2), state, None
        mc = re.search(r'[?&]code=([a-f0-9]{16,})', body)
        if mc:
            return mc.group(1), state, None
        # consent form
        tok = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', body)
        if not tok:
            tok = re.search(r'value="([^"]+)"[^>]*name="authenticity_token"', body)
        if not tok:
            tok = re.search(r'"authenticity_token"\s*:\s*"([^"]+)"', body)
        if not tok:
            title = re.search(r'<title>([^<]*)', body)
            return None, state, f'consent without authenticity_token (len={len(body)}) title={title.group(1) if title else "?"}'
        fields = {'authorize': '1', 'authenticity_token': tok.group(1),
                  'client_id': client_id, 'state': state, 'scope': scope}
        st2, h2, body2 = self.post_form(url, fields)
        self.detail.append(f'consent http={st2} loc={h2.get("Location", "")[:80]}')
        loc2 = h2.get('Location', '')
        if st2 in (301, 302):
            code = self._code_from(loc2)
            if code:
                return code, state, None
            return None, state, f'consent redirect without code: {loc2[:150]}'
        m = re.search(r'oauth/github\?code=([a-f0-9]{16,})[^"\']*state=([A-Za-z0-9_\-]+)', body2)
        if m:
            return m.group(1), m.group(2), None
        mref = re.search(r'url=([^"&]+)\?code=([a-f0-9]+)', body2)
        if mref:
            return mref.group(2), state, None
        mc = re.search(r'[?&]code=([a-f0-9]{16,})', body2)
        if mc:
            return mc.group(1), state, None
        return None, state, f'consent http={st2} len={len(body2)}: {body2[:250]}'

    @staticmethod
    def _code_from(loc):
        if not loc:
            return None
        q = urllib.parse.urlparse(loc).query
        return urllib.parse.parse_qs(q).get('code', [None])[0]
