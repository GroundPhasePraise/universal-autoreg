# -*- coding: utf-8 -*-
"""Vani.ai autoreg — cloakbrowser native turnstile + voidash/t-online email
Flow: /login?next=/chat -> email + native TS token -> Check your email -> code/link -> session
"""
import sys, re, json, time, random, string, os
import requests

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'https://c.vani.ai'
LOGIN = BASE + '/login?next=%2Fchat'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vani_accounts.jsonl')
VOID = 'https://api.voidash.com/api/v1'
IMAP_POOL = r'C:\Users\User\Desktop\avtoreg\working_mails.txt'

r = lambda n: ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def make_voidash():
    d = requests.post(VOID + '/inboxes', json={'domain': 'voidash.bond'}, timeout=30).json()
    return ('voidash', d['address'], d['session_key'])

def load_tonline(n=1):
    used = set()
    if os.path.exists('used_emails.txt'):
        used = set(l.strip() for l in open('used_emails.txt') if l.strip())
    out = []
    for line in open(IMAP_POOL, encoding='utf-8'):
        line = line.strip()
        if ':' not in line or line.startswith('#'):
            continue
        em, pw = line.split(':', 1)
        if '-' in em.split('@')[0] or em in used:  # dash-алиасы мертвы
            continue
        out.append(('t-online', em, pw))
        if len(out) >= n:
            break
    return out

def poll_voidash(key, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            msgs = requests.get(VOID + '/messages', headers={'Authorization': 'Bea' + 'rer ' + key}, timeout=30).json()
            items = msgs if isinstance(msgs, list) else msgs.get('messages', msgs.get('data', []))
            for m in items:
                body = json.dumps(m, ensure_ascii=False)
                if 'vani' in body.lower():
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
            typ, data = M.search(None, '(SUBJECT "Vani")')
            ids = data[0].split()
            if not ids:
                typ, data = M.search(None, 'ALL')
                ids = data[0].split()[-5:]
            for i in ids[-5:]:
                typ, md = M.fetch(i, '(RFC822)')
                msg = emlib.message_from_bytes(md[0][1])
                frm = str(msg.get('From', ''))
                if 'vani' not in frm.lower():
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

def extract_code_link(mailjson):
    code = None
    link = None
    lk = re.search(r'https://c\.vani\.ai/[^\s"\\<]+', mailjson)
    if lk:
        link = lk.group(0).replace('\\u0026', '&').replace('\\/', '/').replace('\\u003d', '=')
    # 6-digit code — в тексте, часто крупным шрифтом; ищем изолированные 6 цифр
    for m in re.finditer(r'(?:code[^0-9]{0,40}|>)\s*([0-9]{6})\s*(?:<|$|[^0-9])', mailjson, re.I):
        code = m.group(1)
        break
    if not code:
        m = re.search(r'\b(\d{6})\b', re.sub(r'https?://\S+', '', mailjson))
        if m:
            code = m.group(1)
    return code, link

def run(n, provider='voidash'):
    import cloakbrowser
    okc = 0
    for i in range(n):
        res = {'ok': False, 'ts': int(time.time()), 'provider': provider}
        b = None
        try:
            if provider == 'voidash':
                kind, emailaddr, cred = make_voidash()
            else:
                kind, emailaddr, cred = load_tonline(1)[0]
            res['email'] = emailaddr
            print(f'[{i}] email={emailaddr}')
            b = cloakbrowser.launch(headless=True)
            pg = b.new_page()
            pg.goto(LOGIN, wait_until='domcontentloaded', timeout=60000)
            pg.wait_for_selector('input[type=email]', timeout=25000)
            pg.wait_for_timeout(2000)
            # cookie banner accept
            try:
                btn = pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').trim()==='Accept'); if(b){b.click();return 1;} return 0; }""")
            except Exception:
                pass
            pg.fill('input[type=email]', emailaddr)
            # ждём нативный turnstile токен в hidden input
            tok = None
            for _ in range(50):
                v = pg.evaluate("() => document.querySelector('input[name=turnstile_token]')?.value?.length || 0")
                if v and v > 50:
                    tok = v
                    break
                pg.wait_for_timeout(2500)
            res['ts_token_len'] = tok or 0
            if not tok:
                res['err'] = 'turnstile token timeout'
                print('  TS timeout')
                raise StopIteration
            pg.wait_for_timeout(1000)
            pg.evaluate("() => { const b=[...document.querySelectorAll('button')].find(e=>(e.innerText||'').includes('Email me a sign-in')); b.click(); }")
            pg.wait_for_timeout(9000)
            body = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:400]
            res['after_submit'] = body
            if 'Check your email' not in body and 'code' not in body.lower():
                res['err'] = 'no confirmation: ' + body[:200]
                print('  FAIL submit:', body[:150])
                raise StopIteration
            print('  confirmation OK, polling mail...')
            mail = poll_voidash(cred, 240) if provider == 'voidash' else poll_imap_tonline(emailaddr, cred, 240)
            if not mail:
                res['err'] = 'no email'
                raise StopIteration
            open(f'mail_{i}.json', 'w', encoding='utf-8').write(mail)
            code, link = extract_code_link(mail)
            res['code'] = code
            res['link'] = (link or '')[:140]
            print(f'  code={code} link={(link or "")[:80]}')
            verified = False
            if code:
                # ввод кода на странице
                try:
                    inputs = pg.evaluate("() => [...document.querySelectorAll('input')].map(e=>({t:e.type,n:e.name,ml:e.maxLength}))")
                    res['code_inputs'] = inputs
                    filled = False
                    for idx, inp in enumerate(inputs):
                        if inp.get('ml') == 6 or (inp.get('t') == 'text' and inp.get('n', '').lower().find('code') > -1):
                            sel = f"input >> nth={idx}"
                            pg.fill(sel, code)
                            filled = True
                            break
                    if not filled:
                        # OTP-style раздельные боксы
                        boxes = pg.query_selector_all("input[maxlength='1']")
                        if len(boxes) >= 6:
                            for j, ch in enumerate(code):
                                boxes[j].fill(ch)
                            filled = True
                    if filled:
                        pg.wait_for_timeout(2000)
                        pg.evaluate("() => { const b=[...document.querySelectorAll('button')].find(e=>/verify|continue|sign in|submit/i.test(e.innerText||'')); if(b) b.click(); }")
                        pg.wait_for_timeout(8000)
                except Exception as e:
                    res['code_err'] = str(e)[:120]
                body2 = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:300]
                res['after_code'] = body2
                if pg.url.rstrip('/').endswith('chat') or 'chat' in pg.url or 'welcome' in body2.lower() or 'new chat' in body2.lower():
                    verified = True
            if not verified and link:
                pg.goto(link, wait_until='domcontentloaded', timeout=60000)
                pg.wait_for_timeout(8000)
                body3 = re.sub(r'\s+', ' ', pg.evaluate('() => document.body.innerText'))[:300]
                res['after_link'] = body3
                res['final_url'] = pg.url
                if '/login' not in pg.url:
                    verified = True
            if verified:
                cks = pg.context.cookies() if hasattr(pg, 'context') else pg.evaluate('() => document.cookie')
                res['cookies'] = cks if isinstance(cks, list) else str(cks)[:500]
                res['final_url'] = pg.url
                res['ok'] = True
                okc += 1
                print(f'  [{i}] OK verified, url={pg.url}')
            else:
                res['err'] = res.get('err') or 'not verified'
                pg.screenshot(path=f'fail_{i}.png')
                print(f'  [{i}] FAIL: {res.get("err")}')
        except StopIteration:
            pass
        except Exception as e:
            res['err'] = str(e)[:200]
            print(f'  [{i}] EXC: {str(e)[:150]}')
        finally:
            if b:
                try:
                    b.close()
                except Exception:
                    pass
        with open(OUT, 'a', encoding='utf-8') as f:
            f.write(json.dumps(res, ensure_ascii=False) + '\n')
        if res.get('email'):
            with open('used_emails.txt', 'a') as f:
                f.write(res['email'] + '\n')
        time.sleep(random.randint(5, 12))
    print(f'DONE ok={okc}/{n}')

if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    provider = sys.argv[2] if len(sys.argv) > 2 else 'voidash'
    run(n, provider)
