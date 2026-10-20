# -*- coding: utf-8 -*-
"""Kiro Free farm: mass Builder ID registration via incognito CDP contexts.
Usage: python bid_farm.py N
Flow per account: signin->BuilderID->email->name->IMAP OTP->password->kiro home.
Handles: existing-account bounce, TM captcha (screenshot+VL), rate pacing.
State: bid_accounts.jsonl (results), bid_farm_used.txt (consumed mails)."""
import base64, email.utils, imaplib, json, random, re, string, sys, time, urllib.request, websocket

PORT = 9341
BASE = r'C:\Users\User\tmp\aws_kiro'
MAILS = r'C:\Users\User\Desktop\avtoreg\working_mails.txt'
USED = BASE + r'\bid_farm_used.txt'
OUT = BASE + r'\bid_accounts.jsonl'
MAILPWDS = {}
for line in open(MAILS, encoding='utf-8'):
    line = line.strip()
    if not line or line.startswith('#') or '@' not in line:
        continue
    parts = line.replace(';', ':').split(':', 1)
    MAILPWDS[parts[0].strip().lower()] = parts[1].strip()

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
NAMES = [('Lukas', 'Braun'), ('Jonas', 'Weber'), ('Felix', 'Hoffmann'), ('Maximilian', 'Schaefer'),
         ('Paul', 'Neumann'), ('Leon', 'Winter'), ('Elias', 'Krause'), ('Ben', 'Sommer'),
         ('Finn', 'Albrecht'), ('Noah', 'Brandt'), ('Tim', 'Vogel'), ('Jan', 'Seidel'),
         ('Nils', 'Horn'), ('Kai', 'Otto'), ('Malte', 'Winkler')]

def used_set():
    try:
        return set(open(USED, encoding='utf-8').read().split())
    except FileNotFoundError:
        return set()

def pick_mail(used):
    items = list(MAILPWDS.items())
    random.shuffle(items)
    for em, pw in items:
        if not em.endswith('@t-online.de') or '-' in em.split('@')[0]:
            continue
        if em in used:
            continue
        return em, pw
    return None, None

ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=8))
bws = websocket.create_connection(ver['webSocketDebuggerUrl'], timeout=60, suppress_origin=True)
bws.settimeout(60)
mid = [0]
def bsend(method, params=None, sess=None):
    mid[0] += 1
    msg = {'id': mid[0], 'method': method, 'params': params or {}}
    if sess:
        msg['sessionId'] = sess
    bws.send(json.dumps(msg))
    while True:
        m = json.loads(bws.recv())
        if m.get('id') == mid[0]:
            return m.get('result', {})

def pev(expr, sess):
    r = bsend('Runtime.evaluate', {'expression': expr, 'returnByValue': True}, sess)
    if 'exceptionDetails' in r:
        return 'EXC:' + str(r['exceptionDetails'])[:100]
    return r.get('result', {}).get('value')

def ptype(text, sess):
    bsend('Input.insertText', {'text': text}, sess)

def vl_read(png_bytes):
    b64 = base64.b64encode(png_bytes).decode()
    payload = {'model': 'qwen3-vl-plus', 'messages': [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
        {'type': 'text', 'text': 'Read the distorted captcha text. Reply ONLY with the exact string, no explanation.'}]}],
        'max_tokens': 40, 'temperature': 0.0}
    req = urllib.request.Request('http://127.0.0.1:16432/v1/chat/completions', data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer EMPTY'})
    r = json.load(urllib.request.urlopen(req, timeout=90))
    return r['choices'][0]['message']['content'].strip()

def find_iframe_target(ctx_id):
    r = bsend('Target.getTargets')
    for ti in r.get('targetInfos', []):
        if ti.get('type') == 'iframe' and 'threat-mitigation' in ti.get('url', '') and ti.get('browserContextId') == ctx_id:
            return ti['targetId']
    return None

def solve_captcha(sess, ctx_id, tag):
    """Screenshot the TM iframe img region via main target, VL read, fill in iframe. Returns True if solved/absent."""
    for rnd in range(4):
        ift = find_iframe_target(ctx_id)
        if not ift:
            # maybe need Verify click on main page
            v = pev("""(() => {
              for (const b of document.querySelectorAll('button, a, [role=button]')) {
                const t = (b.innerText||'').trim();
                if (b.offsetParent !== null && /^Verify$/i.test(t)) { b.click(); return 'clicked'; }
              }
              return 'nf';
            })()""", sess)
            print(f'  [{tag}] no iframe; verify={v}', flush=True)
            time.sleep(4)
            ift = find_iframe_target(ctx_id)
            if not ift:
                return True  # no challenge at all
        ifs = bsend('Target.attachToTarget', {'targetId': ift, 'flatten': True})['sessionId']
        time.sleep(2)
        has_input = pev("(() => { const i = document.querySelector('input[name=captchaGuess]'); return !!(i && i.offsetParent !== null); })()", ifs)
        if not has_input:
            print(f'  [{tag}] iframe no input yet', flush=True)
            time.sleep(4)
            has_input = pev("(() => { const i = document.querySelector('input[name=captchaGuess]'); return !!(i && i.offsetParent !== null); })()", ifs)
        inner = pev("""(() => {
          const imgs = Array.from(document.querySelectorAll('img')).filter(im => im.width > 50 && im.offsetParent !== null);
          if (!imgs.length) return null;
          const b = imgs[0].getBoundingClientRect();
          return JSON.stringify([b.x, b.y, b.width, b.height]);
        })()""", ifs)
        rect = pev("""(() => {
          const f = document.querySelector('iframe[src*="threat-mitigation"]');
          if (!f) return null;
          const b = f.getBoundingClientRect();
          return JSON.stringify([b.x, b.y, b.width, b.height]);
        })()""", sess)
        if not inner or not rect:
            print(f'  [{tag}] no geometry', flush=True)
            time.sleep(2)
            continue
        ix, iy, iw, ih = json.loads(inner)
        fx, fy, fw, fh = json.loads(rect)
        shot = bsend('Page.captureScreenshot', {'format': 'png', 'clip': {'x': fx + ix, 'y': fy + iy, 'width': iw, 'height': ih, 'scale': 2}}, sess)
        if not shot.get('data'):
            print(f'  [{tag}] no shot', flush=True)
            time.sleep(2)
            continue
        png = base64.b64decode(shot['data'])
        ans = re.sub(r'[^A-Za-z0-9]', '', vl_read(png))
        print(f'  [{tag}] captcha VL={ans}', flush=True)
        pev(f"""(() => {{
          const inp = document.querySelector('input[name=captchaGuess]');
          if (!inp) return;
          const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(inp), 'value');
          d.set.call(inp, {json.dumps(ans)});
          inp.dispatchEvent(new Event('input', {{bubbles: true}}));
          inp.dispatchEvent(new Event('change', {{bubbles: true}}));
          for (const b of document.querySelectorAll('button')) if (/^submit$/i.test((b.innerText||'').trim())) b.click();
        }})()""", ifs)
        time.sleep(8)
        body = str(pev("document.body.innerText.slice(0,200)", sess))
        if find_iframe_target(ctx_id) is None or 'Invalid captcha' not in body:
            print(f'  [{tag}] captcha cleared', flush=True)
            return True
    return False

def fetch_otp(em, mpwd, subject_terms, timeout_s=180):
    deadline = time.time() + timeout_s
    seen = set()
    while time.time() < deadline:
        try:
            M = imaplib.IMAP4_SSL('secureimap.t-online.de', 993)
            M.login(em, mpwd)
            M.select('INBOX')
            _, d = M.search(None, 'ALL')
            ids = d[0].split()
            now = time.time()
            for i in reversed(ids[-8:]):
                _, msg = M.fetch(i, '(RFC822)')
                raw = msg[0][1].decode('utf-8', 'replace')
                low = raw.lower()
                if not any(t in low for t in subject_terms):
                    continue
                dt = re.search(r'Date: ([^\r\n]+)', raw)
                age = None
                if dt:
                    try:
                        age = now - email.utils.parsedate_to_datetime(dt.group(1)).timestamp()
                    except Exception:
                        pass
                if age is not None and age > 400:
                    continue
                flat = raw.replace('=\r\n', '').replace('=\n', '')
                m = re.search(r'font-size:\s*36px[^>]*>\s*(\d{6})\s*<', flat) or \
                    re.search(r'font-weight:\s*bold[^>]*>\s*(\d{6})\s*<', flat) or \
                    re.search(r'(?:verification code|code)[^\d]{0,60}(\d{6})', flat, re.I)
                if m and m.group(1) not in seen:
                    M.logout()
                    return m.group(1)
            M.logout()
        except Exception as e:
            print('  imap:', str(e)[:70], flush=True)
        time.sleep(18)
    return None

def cont(sess, rx='/^(Continue|Verify|Submit|Create|Sign in)$/'):
    return pev("""(() => {
      for (const b of document.querySelectorAll('button')) {
        const t=(b.innerText||'').trim();
        if (b.offsetParent!==null && %s.test(t)) { b.click(); return t; }
      }
      return 'nf';
    })()""" % rx, sess)

def farm_one(em, mpwd):
    rec = {'email': em, 'ts': time.strftime('%Y-%m-%d %H:%M'), 'ok': False, 'stage': 'start'}
    ctx_id = bsend('Target.createBrowserContext')['browserContextId']
    target_id = bsend('Target.createTarget', {'url': 'https://app.kiro.dev/signin', 'browserContextId': ctx_id})['targetId']
    sess = bsend('Target.attachToTarget', {'targetId': target_id, 'flatten': True})['sessionId']
    try:
        bsend('Page.enable', sess=sess)
        time.sleep(13)
        pev("""(() => {
          const els = Array.from(document.querySelectorAll('button, a, [role=button], div, li, span'));
          let card = null;
          for (const el of els) { const t=(el.innerText||'').trim(); if (t.startsWith('Builder ID') && t.length<40) card = el; }
          if (!card) return;
          const scope = card.closest('div,li') || card.parentElement;
          for (const b of (scope?scope.querySelectorAll('button, a'):[])) { if (/sign in/i.test((b.innerText||'').trim())) { b.click(); return; } }
          card.click();
        })()""", sess)
        time.sleep(11)
        rec['stage'] = 'platform'
        # captcha before email?
        if find_iframe_target(ctx_id):
            solve_captcha(sess, ctx_id, 'pre-email')
        # email
        pev("(() => { const el = document.querySelector('input[type=email]'); if (el) el.focus(); })()", sess)
        time.sleep(0.3)
        ptype(em, sess)
        time.sleep(0.5)
        cont(sess)
        time.sleep(6)
        loc = str(pev('location.href', sess))
        body = str(pev("document.body ? document.body.innerText.slice(0,300) : ''", sess))
        if 'signin' in loc and 'platform' in loc and ('password' in body.lower() or 'Sign in' in body):
            # account already exists -> it asks to sign in; abort, burn mail
            rec['stage'] = 'exists'
            print('  exists, skip', flush=True)
            return rec
        if find_iframe_target(ctx_id):
            solve_captcha(sess, ctx_id, 'after-email')
        # name step
        rec['stage'] = 'name'
        pev("(() => { const el = Array.from(document.querySelectorAll('input')).find(i=>i.offsetParent!==null && i.type==='text'); if (el) el.focus(); })()", sess)
        time.sleep(0.3)
        first, last = random.choice(NAMES)
        ptype(f'{first} {last}', sess)
        time.sleep(0.4)
        cont(sess)
        time.sleep(6)
        # OTP step
        rec['stage'] = 'otp'
        code = fetch_otp(em, mpwd, ['aws', 'amazon', 'builder'])
        if not code:
            rec['stage'] = 'otp-fail'
            print('  no otp', flush=True)
            return rec
        pev("""(() => {
          const inp = Array.from(document.querySelectorAll('input')).find(i => i.offsetParent !== null && i.type === 'text');
          if (!inp) return;
          const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(inp), 'value');
          d.set.call(inp, '%s');
          inp.dispatchEvent(new Event('input', {bubbles: true}));
          inp.dispatchEvent(new Event('change', {bubbles: true}));
        })()""" % code, sess)
        time.sleep(0.5)
        cont(sess)
        time.sleep(7)
        if find_iframe_target(ctx_id):
            solve_captcha(sess, ctx_id, 'after-otp')
        # password step
        rec['stage'] = 'password'
        pw = 'Kx' + ''.join(random.choices(string.ascii_lowercase, k=7)) + str(random.randint(10, 99)) + 'Rt!'
        filled = pev("""(() => {
          const inps = Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent !== null && i.type === 'password');
          if (inps.length < 2) return 'nf:' + inps.length;
          const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(inps[0]), 'value');
          for (const el of inps.slice(0, 2)) {
            d.set.call(el, %s);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
          }
          const cb = Array.from(document.querySelectorAll('input')).find(i => i.type === 'checkbox' && !i.checked);
          if (cb) cb.click();
          return 'ok';
        })()""" % json.dumps(pw), sess)
        print('  pwd fill:', filled, flush=True)
        if str(filled).startswith('nf'):
            rec['stage'] = 'pwd-nf'
            return rec
        time.sleep(0.5)
        cont(sess)
        # wait for kiro redirect
        for i in range(14):
            time.sleep(5)
            loc = str(pev('location.href', sess))
            if 'kiro' in loc:
                break
            if find_iframe_target(ctx_id):
                solve_captcha(sess, ctx_id, 'post-pwd')
        rec['final_url'] = loc[:120]
        if 'kiro' in loc:
            rec['ok'] = True
            rec['stage'] = 'kiro_home'
            rec['password'] = pw
        else:
            body = str(pev("document.body ? document.body.innerText.slice(0,200) : ''", sess))
            rec['stage'] = 'stuck'
            rec['body'] = body[:150]
    except Exception as e:
        rec['stage'] = 'err:' + str(e)[:90]
    finally:
        try:
            bsend('Target.disposeBrowserContext', {'browserContextId': ctx_id})
        except Exception:
            pass
    return rec

used = used_set()
done = 0
for n in range(N):
    em, mpwd = pick_mail(used)
    if not em:
        print('mails exhausted', flush=True)
        break
    used.add(em)
    with open(USED, 'a', encoding='utf-8') as f:
        f.write(em + '\n')
    print(f'=== [{n+1}/{N}] {em} ===', flush=True)
    rec = farm_one(em, mpwd)
    with open(OUT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print('RESULT:', rec['stage'], rec.get('final_url', ''), flush=True)
    if rec['ok']:
        done += 1
    time.sleep(random.randint(25, 45))
print(f'FARM DONE: {done}/{N} ok', flush=True)
bws.close()
