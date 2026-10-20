# -*- coding: utf-8 -*-
"""type.com autoreg — WorkOS AuthKit (auth.type.com) + cloakbrowser
Flow: /onboarding -> sign-up (name+email) -> password -> [email verify?] -> session
Usage: python type_reg.py N [voidash|tonline]
"""
import sys, re, json, time, random, string, os, urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'type_accounts.jsonl')
VOID = 'https://api.voidash.com/api/v1'
IMAP_POOL = r'C:\Users\User\Desktop\avtoreg\working_mails.txt'
START = 'https://type.com/onboarding'

# ---- 2no.pl phone (reuse reserved number, expires 2026-10-13T20:47) ----
NO_EMAIL = 'borek1cd9d5@eq.nexushint.com'
NO_PASS = 'YOUR_PASSWORD'

def _no_accounts():
    """Rotate 2no accounts: prefer accounts with FEWEST active reservations (<3 limit).
    Active = number expiry in the future. An account whose numbers are all 'used' for
    signup can still FRESH-reserve if it has free slots."""
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    act = {}   # email -> active count
    creds = {} # email -> password
    try:
        for line in open(os.path.join(HERE, '2no_accounts.jsonl'), encoding='utf-8'):
            a = json.loads(line)
            if not a.get('password'):
                continue
            creds[a['email']] = a['password']
            exp = str(a.get('expires') or '')
            act.setdefault(a['email'], 0)
            if exp > now:
                act[a['email']] += 1
    except Exception:
        pass
    try:
        c = json.load(open(os.path.join(HERE, '_reuse_candidates.json'), encoding='utf-8'))
        for x in c:
            creds.setdefault(x['email'], x['pass'])
            act.setdefault(x['email'], 0)
            if str(x.get('exp') or '') > now:
                act[x['email']] += 1
    except Exception:
        pass
    ranked = sorted(creds.items(), key=lambda kv: act.get(kv[0], 0))
    if ranked:
        return ranked
    return [(NO_EMAIL, NO_PASS)]

_NO_ACCS = _no_accounts()
_NO_IDX = [0]

def no_cred():
    e, p = _NO_ACCS[_NO_IDX[0] % len(_NO_ACCS)]
    _NO_IDX[0] += 1
    return e, p
PHONE = '+48459079062'
PHONE_ID = 108963
PY311 = r'C:/Users/User/AppData/Local/Programs/Python/Python311/python.exe'

def make_voidash():
    import requests
    dom = os.environ.get('VOID_DOMAIN', 'voidash.bond')
    d = requests.post(VOID + '/inboxes', json={'domain': dom}, timeout=30).json()
    return d['address'], d['session_key']

def poll_tempmail(token, timeout=300):
    """poll tempmail.lol inbox; return raw body of first mail containing 6 digits"""
    import time as _t
    url = 'https://api.tempmail.lol/v2/inbox?token=' + token
    t0 = _t.time()
    while _t.time() - t0 < timeout:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
            for m in (d.get('emails') or []):
                body = (m.get('html_body') or '') + (m.get('text_body') or '') + str(m.get('subject') or '')
                if re.search(r'(?<!\d)\d{6}(?!\d)', re.sub(r'https?://\S+', '', body)):
                    print('  tempmail mail:', str(m.get('subject'))[:60])
                    return body
        except Exception as e:
            print('  tempmail poll err:', str(e)[:60])
        _t.sleep(8)
    return None


def load_tonline(n=1):
    used = set()
    uf = os.path.join(HERE, 'used_emails.txt')
    if os.path.exists(uf):
        used = set(l.strip() for l in open(uf) if l.strip())
    out = []
    for line in open(IMAP_POOL, encoding='utf-8'):
        line = line.strip()
        if ':' not in line or line.startswith('#'):
            continue
        em, pw = line.split(':', 1)
        if '-' in em.split('@')[0] or em in used:
            continue
        out.append((em, pw))
        if len(out) >= n:
            break
    return out

def poll_voidash(key, timeout=240):
    import requests
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            msgs = requests.get(VOID + '/messages', headers={'Authorization': 'Bea' + 'rer ' + key}, timeout=30).json()
            items = msgs if isinstance(msgs, list) else msgs.get('messages', msgs.get('data', []))
            for m in items:
                body = json.dumps(m, ensure_ascii=False)
                if 'type' in body.lower():
                    return body
        except Exception:
            pass
        time.sleep(5)
    return None

def poll_imap_tonline(email, pw, timeout=240):
    import imaplib, email as emlib
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            M = imaplib.IMAP4_SSL('secureimap.t-online.de', 993)
            M.login(email, pw)
            M.select('INBOX')
            typ, data = M.search(None, '(FROM "type.com")')
            ids = data[0].split()
            if not ids:
                typ, data = M.search(None, 'ALL')
                ids = data[0].split()[-6:]
            for i in ids[-6:]:
                typ, md = M.fetch(i, '(RFC822)')
                msg = emlib.message_from_bytes(md[0][1])
                frm = str(msg.get('From', ''))
                if 'type.com' not in frm.lower():
                    continue
                body = ''
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == 'text/html':
                            body = part.get_payload(decode=True).decode('utf-8', 'replace')
                            break
                else:
                    body = msg.get_payload(decode=True).decode('utf-8', 'replace')
                M.logout()
                return json.dumps({'from': frm, 'subject': str(msg.get('Subject')), 'body': body}, ensure_ascii=False)
            M.logout()
        except Exception as e:
            print('  imap retry:', str(e)[:80])
        time.sleep(8)
    return None

def poll_imap_gmail_fwd(target_email, timeout=240, min_ts=None):
    """OTP via forwardemail catch-all -> YOUR_EMAIL@gmail.com"""
    import imaplib, email as emlib
    from email.utils import parsedate_to_datetime
    GMAIL = 'YOUR_EMAIL@gmail.com'
    APP_PW = os.environ.get('GMAIL_APP_PW', 'YOUR_IMAP_APP_PASSWORD')
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            M = imaplib.IMAP4_SSL('imap.gmail.com', 993)
            M.login(GMAIL, APP_PW)
            M.select('INBOX')
            ids = []
            for q in [f'(TO "{target_email}")', f'(TEXT "{target_email}")']:
                typ, data = M.search(None, q)
                ids = data[0].split()
                if ids:
                    break
            if not ids:
                # Gmail filter may skip INBOX -> search All Mail (\All)
                allbox = None
                typ, boxes = M.list()
                for b in boxes or []:
                    s = b.decode('utf-8', 'replace')
                    if '\\All' in s:
                        allbox = s.split(' "/" ')[-1].strip('"')
                        break
                if allbox:
                    typ, _ = M.select('"%s"' % allbox, readonly=True)
                    if typ == 'OK':
                        for q in [f'(TO "{target_email}")', f'(TEXT "{target_email}")']:
                            typ, data = M.search(None, q)
                            ids = data[0].split()
                            if ids:
                                break
            for i in reversed(ids[-8:]):
                typ, md = M.fetch(i, '(RFC822)')
                msg = emlib.message_from_bytes(md[0][1])
                if min_ts:
                    try:
                        dt = parsedate_to_datetime(str(msg.get('Date', '')))
                        if dt and dt.timestamp() < min_ts - 60:
                            continue
                    except Exception:
                        pass
                body = ''
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == 'text/html':
                            body = part.get_payload(decode=True).decode('utf-8', 'replace')
                            break
                else:
                    body = msg.get_payload(decode=True).decode('utf-8', 'replace')
                M.logout()
                return json.dumps({'from': str(msg.get('From', '')), 'subject': str(msg.get('Subject')), 'body': body}, ensure_ascii=False)
            M.logout()
        except Exception as e:
            print('  gmail retry:', str(e)[:80])
        time.sleep(8)
    return None

def btn_text(pg, pat):
    return f"() => {{ const b=[...document.querySelectorAll('button')].find(e=>/{pat}/i.test((e.innerText||'').trim())); if(b){{b.click();return 1;}} return 0; }}"

def run(n, provider='voidash'):
    import cloakbrowser
    okc = 0
    for i in range(n):
        res = {'ok': False, 'ts': int(time.time()), 'provider': provider}
        b = None
        try:
            if provider == 'voidash':
                emailaddr, cred = make_voidash()
            elif provider == 'custom':
                emailaddr = os.environ.get('EMAIL') or ('otp' + str(random.randint(10000, 99999)) + '@' + os.environ.get('EMAIL_DOMAIN', 'nexuslab.loc.cc'))
                cred = None
            elif provider == 'nl8':
                emailaddr = 'u' + str(random.randint(100000, 999999)) + '@' + os.environ.get('EMAIL_DOMAIN', 'reform.nl8.eu')
                cred = os.environ.get('TEMPMAIL_TOKEN', '')
            else:
                emailaddr, cred = load_tonline(1)[0]
            pw = 'Tp' + ''.join(random.choices(string.ascii_letters, k=6)) + str(random.randint(100, 999)) + 'x'
            res['email'] = emailaddr
            res['password'] = pw
            print(f'[{i}] email={emailaddr}')
            proxy = os.environ.get('PROXY')
            proxy_kwargs = {'proxy': proxy} if proxy else {}
            loc = os.environ.get('LOCALE', 'en-US')
            tz = os.environ.get('TZID')  # e.g. Europe/Amsterdam
            if tz:
                proxy_kwargs['timezone'] = tz
            proxy_kwargs['locale'] = loc
            if os.environ.get('HUMANIZE', '1') == '1':
                proxy_kwargs['humanize'] = True
            b = cloakbrowser.launch(headless=True, **proxy_kwargs)
            pg = b.new_page()
            pg.goto(START, wait_until='domcontentloaded', timeout=60000)
            try:
                pg.wait_for_selector('input[name="first_name"]', timeout=45000)
            except Exception:
                pg.goto(START, wait_until='domcontentloaded', timeout=60000)
                pg.wait_for_selector('input[name="first_name"]', timeout=60000)
            pg.wait_for_timeout(1500)
            fn = random.choice(['Alex', 'Max', 'Nik', 'Sam', 'Leo', 'Ivan', 'Dan', 'Kir', 'Oleg', 'Tim'])
            ln = random.choice(['Morgan', 'Weber', 'Klein', 'Bauer', 'Wolf', 'Stone', 'Reed', 'Cole', 'Fox', 'Lang'])
            pg.fill('input[name="first_name"]', fn)
            pg.fill('input[name="last_name"]', ln)
            pg.fill('input[name="email"]', emailaddr)
            res['name'] = fn + ' ' + ln
            pg.wait_for_timeout(random.randint(800, 2000))
            pg.evaluate(btn_text(pg, r'Продолжить|Continue'))
            # password step
            pg.wait_for_selector('input[name="password"], input[type="password"]', timeout=30000)
            pg.wait_for_timeout(1200)
            pg.fill('input[type="password"]', pw)
            pg.wait_for_timeout(random.randint(800, 1800))
            # submit with retry: flaky Continue click (two 'Продолжить' buttons on page)
            for _att in range(4):
                pg.evaluate(btn_text(pg, r'Продолжить|Continue'))
                pg.wait_for_timeout(4000)
                if 'password' not in pg.url:
                    break
                pg.evaluate("() => { const f=document.querySelector('form'); if(f) f.requestSubmit(); }")
                pg.wait_for_timeout(3500)
                if 'password' not in pg.url:
                    break
                try:
                    pg.locator('button[type="submit"]').first.click(timeout=3000)
                    pg.wait_for_timeout(3500)
                except Exception:
                    pass
                if 'password' not in pg.url:
                    break
            pg.wait_for_timeout(3000)
            body = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:500]
            res['after_password'] = body
            res['url1'] = pg.url
            print('  url:', pg.url[:110])
            print('  body:', body[:200])
            blocked = 'заблокирован' in body or 'access blocked' in body.lower() or 'обратитесь в службу поддержки' in body
            if blocked:
                res['err'] = 'signals block'
                pg.screenshot(path=os.path.join(HERE, f'fail_{i}.png'))
                print('  BLOCKED')
                raise StopIteration
            if 'sign-up/password' in pg.url:
                res['err'] = 'password submit failed (still on form)'
                pg.screenshot(path=os.path.join(HERE, f'failpw_{i}.png'))
                print('  STUCK ON PASSWORD FORM')
                raise StopIteration
            # email verification step?
            if 'code' in body.lower() or 'код' in body.lower() or 'email' in pg.url:
                print('  polling mail for verification...')
                if provider == 'voidash':
                    mail = poll_voidash(cred, 240)
                elif provider == 'custom':
                    mail = poll_imap_gmail_fwd(emailaddr, 300)
                elif provider == 'nl8':
                    mail = poll_tempmail(cred, 300)
                else:
                    mail = poll_imap_tonline(emailaddr, cred, 240)
                if mail:
                    open(os.path.join(HERE, f'mail_{i}.json'), 'w', encoding='utf-8').write(mail)
                    m = re.search(r'\b(\d{6})\b', re.sub(r'https?://\S+', '', mail))
                    code = m.group(1) if m else None
                    res['code'] = code
                    lk = re.search(r'https://[^"\\\s<]*(?:verify|confirm|otp|auth)[^"\\\s<]*', mail)
                    res['link'] = (lk.group(0) if lk else '')[:160]
                    print(f'  code={code}')
                    if code:
                        for otp_try in range(3):
                            try:
                                pg.wait_for_timeout(1500)
                                # fill OTP per-char with playwright fill (no keyboard race)
                                vis = pg.locator('input:visible')
                                n_in = vis.count()
                                res['otp_inputs_n'] = n_in
                                if n_in >= 6:
                                    for k, ch in enumerate(code[:6]):
                                        vis.nth(k).fill(ch)
                                elif n_in >= 1:
                                    vis.first.fill(code)
                                pg.wait_for_timeout(6000)  # auto-submit window
                                if 'email-verification' in pg.url:
                                    pg.evaluate(btn_text(pg, r'Продолжить|Continue|Verify|Подтвердить'))
                                    pg.wait_for_timeout(6000)
                                body_now = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:400]
                                if 'email-verification' not in pg.url or 'Invalid one-time code' not in body_now:
                                    break
                                # invalid code -> wait countdown, resend, re-poll fresh code
                                print('  OTP INVALID, resend attempt %d' % (otp_try + 1), flush=True)
                                pg.wait_for_timeout(30000)
                                pg.evaluate("""() => { const l=[...document.querySelectorAll('a,button,span,div')].find(e=>e.children.length===0 && /Didn.t receive|request a new|Не получили/i.test((e.innerText||'').trim())); if(l) l.click(); }""")
                                rs_ts = time.time()
                                pg.wait_for_timeout(3000)
                                code = None
                                mail2 = poll_imap_gmail_fwd(emailaddr, 240, min_ts=rs_ts)
                                if mail2:
                                    m2 = re.search(r'\b(\d{6})\b', re.sub(r'https?://\S+', '', mail2))
                                    code = m2.group(1) if m2 else None
                                    res['code'] = code
                                    print(f'  fresh code={code}', flush=True)
                                if not code:
                                    break
                            except Exception as e:
                                res['code_err'] = str(e)[:120]
                                break
            # ---- phone verification step (WorkOS SMS via 2no.pl) ----
            pg.wait_for_timeout(3000)
            body_ph = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:400]
            if 'телефон' in body_ph.lower() or 'phone' in body_ph.lower():
                print('  PHONE step:', body_ph[:150])
                ph_inputs = pg.evaluate("() => [...document.querySelectorAll('input')].filter(e=>e.offsetParent&&e.type!=='hidden').map(e=>({t:e.type,ml:e.maxLength,n:e.name,ph:e.placeholder}))")
                res['phone_inputs'] = ph_inputs
                print('  phone inputs:', ph_inputs)
                # start SMS reader FIRST — chrome launch+login warms up while we fill fields
                import subprocess
                from datetime import datetime, timedelta
                # reserve a FRESH 2nd-no number per registration (WorkOS binds phone to account)
                stamp = int(time.time())
                rfile = os.path.join(HERE, f'reserve_{stamp}.json')
                cfile = os.path.join(HERE, f'smscode_{stamp}.json')
                min_ts = (datetime.now() - timedelta(minutes=120)).isoformat(timespec='seconds')
                smslog = open(os.path.join(HERE, f'sms_reserve_{stamp}.log'), 'w', encoding='utf-8')
                sms_proc = subprocess.Popen(
                    [PY311, os.path.join(HERE, 'sms2no_reserve.py'), *no_cred(), rfile, cfile, '360', min_ts],
                    stdout=smslog, stderr=subprocess.STDOUT, text=True,
                    cwd=HERE, env={**os.environ, 'PYTHONPATH': '', 'PYTHONIOENCODING': 'utf-8'})
                # wait for reservation (2no login + reserve/reuse ~40-120s)
                phone_dyn = None
                t0 = time.time()
                while time.time() - t0 < 380:
                    if os.path.exists(rfile):
                        try:
                            phone_dyn = json.load(open(rfile, encoding='utf-8'))
                            break
                        except Exception:
                            pass
                    if sms_proc.poll() is not None and not os.path.exists(rfile):
                        break  # reader died — check sms_reserve_*.log
                    time.sleep(2)
                try:
                    smslog.close()
                except Exception:
                    pass
                if not phone_dyn or not phone_dyn.get('phone'):
                    res['err'] = 'reserve timeout'
                    raise RuntimeError('2no reserve timeout')
                PHONE_DYN = str(phone_dyn['phone'])
                res['phone'] = PHONE_DYN
                res['number_id'] = phone_dyn.get('number_id')
                print('  reserved:', PHONE_DYN)
                # split into country_code + local_number (WorkOS split fields); 2no free pool = PL
                if PHONE_DYN.startswith('+48'):
                    cc, local = '+48', re.sub(r'\D', '', PHONE_DYN[3:])
                else:
                    m_ph = re.match(r'(\+\d{1,3})(\d+)', PHONE_DYN)
                    cc, local = m_ph.group(1), m_ph.group(2)
                filled_ph = pg.evaluate("""(v) => {
                    const inp=document.querySelector('input[name=country_code]');
                    if(!inp) return 0; inp.focus();
                    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                    setter.call(inp, v); inp.dispatchEvent(new Event('input',{bubbles:true}));
                    inp.dispatchEvent(new Event('change',{bubbles:true})); return 1;
                }""", cc)
                pg.wait_for_timeout(500)
                ln = pg.query_selector('input[name=local_number]')
                if ln:
                    ln.click()
                    pg.keyboard.type(local, delay=130)
                    filled_ph += 1
                pg.wait_for_timeout(800)
                ph_vals = pg.evaluate("() => JSON.stringify({cc:document.querySelector('input[name=country_code]')?.value, ln:document.querySelector('input[name=local_number]')?.value})")
                res['phone_values'] = ph_vals
                print('  phone values:', ph_vals)
                res['phone_filled'] = filled_ph
                pg.wait_for_timeout(1200)
                clicked = pg.evaluate(btn_text(pg, r'Send verification|Отправить код|Send verification code|Send code|Продолжить|Continue|Verify'))
                if not clicked:
                    try:
                        pg.get_by_role('button', name=re.compile('send|verification|отправить|continue|продолжить', re.I)).first.click(timeout=5000)
                        clicked = 'locator'
                    except Exception as ce:
                        print('  SEND CLICK FAIL:', str(ce)[:100], flush=True)
                print('  send clicked:', clicked, flush=True)
                pg.wait_for_timeout(5000)
                body_after_send = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:300]
                res['after_phone_send'] = body_after_send
                print('  after send:', body_after_send[:150])
                sms_code = None
                t1 = time.time()
                while time.time() - t1 < 420:
                    if os.path.exists(cfile):
                        try:
                            d = json.load(open(cfile, encoding='utf-8'))
                            sms_code = d.get('code')
                            res['sms_raw'] = json.dumps(d, ensure_ascii=False)[:200]
                            break
                        except Exception:
                            pass
                    if sms_proc.poll() is not None and time.time() - t1 > 30:
                        break  # reader died without code file
                    time.sleep(3)
                try:
                    if sms_proc.poll() is None:
                        sms_proc.kill()
                except Exception:
                    pass
                res['sms_code'] = sms_code
                print('  sms code:', sms_code, '| raw:', str(res.get('sms_raw'))[:120])
                if sms_code:
                    try:
                        pg.evaluate("() => { const inp=[...document.querySelectorAll('input')].find(e=>e.offsetParent && e.type!=='hidden'); if(inp) inp.focus(); }")
                        pg.keyboard.type(sms_code, delay=200)
                    except Exception as e:
                        res['sms_type_err'] = str(e)[:150]
                    pg.wait_for_timeout(12000)  # auto-submit + navigation window
                    try:
                        if re.search(r'Продолжить|Continue|Verify|Подтвердить', pg.evaluate('() => document.body.innerText')):
                            pg.evaluate(btn_text(pg, r'Продолжить|Continue|Verify|Подтвердить'))
                            pg.wait_for_timeout(9000)
                    except Exception:
                        pass  # navigation in flight = good sign
                    try:
                        pg.wait_for_load_state('domcontentloaded', timeout=20000)
                    except Exception:
                        pass
                    try:
                        res['after_phone_code'] = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:300]
                        res['phone_url'] = pg.url
                        print('  after phone code url:', pg.url[:100])
                    except Exception as e:
                        res['phone_state_err'] = str(e)[:120]
            # final state
            res['final_url'] = pg.url
            res['final_body'] = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:400]
            cks = pg.context.cookies()
            res['cookies'] = [{'name': c['name'], 'value': c['value'], 'domain': c.get('domain')} for c in cks] if isinstance(cks, list) else str(cks)[:1000]
            try:
                res['local_storage'] = pg.evaluate("() => JSON.stringify(Object.fromEntries(Object.keys(localStorage).map(k=>[k,(localStorage.getItem(k)||'').slice(0,2000)])))")
            except Exception:
                pass
            pg.screenshot(path=os.path.join(HERE, f'ok_{i}.png'))
            if 'auth.type.com' not in pg.url:
                res['ok'] = True
                okc += 1
                print(f'  [{i}] OK url={pg.url[:100]}')
            else:
                res['err'] = res.get('err') or 'stuck on auth'
                print(f'  [{i}] FAIL {res.get("err")}')
        except StopIteration:
            pass
        except Exception as e:
            res['err'] = str(e)[:250]
            print(f'  [{i}] EXC: {str(e)[:180]}')
        finally:
            if b:
                try:
                    b.close()
                except Exception:
                    pass
        with open(OUT, 'a', encoding='utf-8') as f:
            f.write(json.dumps(res, ensure_ascii=False) + '\n')
        if res.get('email'):
            with open(os.path.join(HERE, 'used_emails.txt'), 'a') as f:
                f.write(res['email'] + '\n')
        time.sleep(random.randint(5, 12))
    print(f'DONE ok={okc}/{n}')

if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    provider = sys.argv[2] if len(sys.argv) > 2 else 'voidash'
    run(n, provider)
