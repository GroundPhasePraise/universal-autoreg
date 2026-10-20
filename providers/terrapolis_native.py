# terrapolis.xyz FULL pipeline: voidash inbox -> browser native reg -> verify email link -> save
import sys, re, json, time, random, string, requests
PAGEURL='https://terrapolis.xyz/register'; OUT='terrapolis_accounts.jsonl'
VOID='https://api.voidash.com/api/v1'
r=lambda n:''.join(random.choices(string.ascii_lowercase+string.digits,k=n))

def make_inbox():
    d=requests.post(VOID+'/inboxes',json={'domain':'voidash.bond'},timeout=30).json()
    return d['address'], d['session_key']

def poll_verify(addr,key,timeout=180):
    t0=time.time()
    while time.time()-t0<timeout:
        try:
            msgs=requests.get(VOID+'/messages',headers={'Authorization':'Bea'+'rer '+key},timeout=30).json()
            items=msgs if isinstance(msgs,list) else msgs.get('messages',msgs.get('data',[]))
            for m in items:
                body=json.dumps(m,ensure_ascii=False)
                lk=re.search(r'https://terrapolis\.xyz/[^\s"\<]+(?:verify|confirm)[^\s"\<]*',body)
                if not lk: lk=re.search(r'(https://terrapolis\.xyz/v[^\s"\<]+)',body)
                if lk: return lk.group(0).replace('\u0026','&').replace('\\/','/')
        except Exception: pass
        time.sleep(6)
    return None

def run(n):
    import cloakbrowser
    proxies=[l.strip() for l in open('terr_proxies_ts3.txt') if l.strip()]
    random.shuffle(proxies)
    b=None; pg=None
    okc=0
    for i in range(n):
        res={'ok':False,'provider':'browser-native+voidash','ts':int(time.time())}
        try:
            if b is not None:
                try: b.close()
                except Exception: pass
            px=proxies[(i//2)%len(proxies)] if proxies else None
            res['proxy']=px
            res['proxy']=px
            try:
                b=cloakbrowser.launch(headless=True,proxy=px) if px else cloakbrowser.launch(headless=True)
            except Exception:
                b=cloakbrowser.launch(headless=True)
            pg=b.new_page()
            addr,key=make_inbox()
            res['email']=addr
            pw=r(14)+'A1!'; res['password']=pw
            for attempt in range(3):
                try:
                    pg.goto(PAGEURL,wait_until='domcontentloaded',timeout=60000)
                    pg.wait_for_selector('input[name=name]',timeout=25000)
                    break
                except Exception:
                    if attempt==2: raise
                    pg.close(); pg=b.new_page(); time.sleep(3)
            pg.wait_for_timeout(2000)
            pg.fill('input[name=name]',r(8).capitalize()); pg.fill('input[name=email]',addr); pg.fill('input[name=password]',pw)
            tok=None
            for _ in range(45):
                v=pg.evaluate("()=>document.querySelector('input[name=captcha]')?.value?.length||0")
                if v>100: tok=v; break
                pg.wait_for_timeout(2500)
            if not tok:
                res['err']='turnstile timeout'; raise StopIteration
            pg.wait_for_timeout(800)
            pg.click('button[type=submit]'); pg.wait_for_timeout(8000)
            res['url']=pg.url
            if 'verify-email' not in pg.url:
                body=re.sub(r'\s+',' ',pg.evaluate('()=>document.body.innerText'))[:200]
                res['err']='no redirect: '+body; raise StopIteration
            lk=poll_verify(addr,key,180)
            if not lk:
                res['err']='no verify email'; raise StopIteration
            res['verify_link']=lk[:120]
            pg.goto(lk,wait_until='domcontentloaded',timeout=60000); pg.wait_for_timeout(5000)
            body=re.sub(r'\s+',' ',pg.evaluate('()=>document.body.innerText'))[:250]
            res['after_verify']=body
            res['ok']=('подтвержд' in body.lower() or 'dashboard' in pg.url or 'успеш' in body.lower() or pg.url!='https://terrapolis.xyz/register')
            res['final_url']=pg.url
            if res['ok']: okc+=1
        except StopIteration: pass
        except Exception as e:
            res['err']='EXC %s: %s'%(type(e).__name__,str(e)[:150])
        print('[%d] %s'%(i,json.dumps(res,ensure_ascii=False)),flush=True)
        open(OUT,'a',encoding='utf-8').write(json.dumps(res,ensure_ascii=False)+'\n')
        time.sleep(random.uniform(3,7))
    try: b.close()
    except Exception: pass
    print('DONE ok=%d/%d'%(okc,n),flush=True)

if __name__=='__main__':
    run(int(sys.argv[1]) if len(sys.argv)>1 else 1)
