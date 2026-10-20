# reg_proxy100.py — волны ×100 через свежие прокси из пула ProxyGrabReform_bot
# python reg_proxy100.py <panel> <start> <count> [idxlist]
import os
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import proxy_patch
n = proxy_patch.apply()
print(f'[proxy] pool={n}', flush=True)
import reg_http as R

R.PANELS.update({
    'careke': 'https://api.careke.cn',
    'budsin': 'https://apichat.budsin.dev',
    'factory': 'https://factory.pub',
    'chengmo': 'https://api.chengmo.cc.cd',
    'vsllm': 'https://vsllm.cc',
    'bluesminds': 'https://api.bluesminds.com',
    'futureppo': 'https://api.futureppo.top',
    'xinjianya': 'https://new.xinjianya.top',
    'wyy22': 'https://www.wyy22.com',
})
R.CID_CACHE.update({
    'careke': 'Ov23lidGyKz1a4vvTJcO',
    'budsin': 'Ov23liRLk2EjkL1U6wBq',
    'factory': 'Ov23liYpDvO0unvs30hv',
    'chengmo': 'Ov23lisqBbgryYRmy9iq',
    'vsllm': 'Ov23lilzfngji58FxRgd',
    'bluesminds': 'Ov23li6dIXgEIlgaZfwe',
    'futureppo': 'Ov23liuf3EDERWtH3z8s',
    'xinjianya': 'Ov23liJMiO2uF9Gd9Y8O',
    'wyy22': 'Ov23li6UR9HGe9xBUCXf',
    'orcarouter': 'Ov23liG25dfcvokSRMvE',
    'justwoker': 'Ov23liBGecTYSePKpXQC',
    'jbbtoken': 'Ov23liuIBUfD02Nbt6vt',
    'jianzhile': 'Iv23li6yE1ijJOPIl3Vq',
    'moyuu': 'Ov23lieXHgDisyeiJk2d',
    'nova': 'Ov23li1gLxcYTVoL0Tjv',
    'aaawinn2': 'Ov23lifMixr1xZGPQf3K',
})
R.PANELS.update({'orcarouter': 'https://www.orcarouter.ai',
    'justwoker': 'https://api.justwoker.icu', 'jbbtoken': 'https://downstream.jbbtoken.cn',
    'jianzhile': 'https://jianzhile.vip', 'moyuu': 'https://moyuu.cc',
    'nova': 'https://nova.vcrauo.com', 'aaawinn2': 'https://aaawinn.xyz'})
R.SMOKE_MODEL.update({'orcarouter': 'gpt-4o-mini'})
R.SMOKE_MODEL.update({'careke': 'grok-4.6', 'budsin': 'claude-sonnet-5',
                      'factory': 'grok-4.7', 'chengmo': 'glm-4.5-air',
                      'bluesminds': 'gpt-4o-mini', 'futureppo': 'gpt-4o-mini',
                      'xinjianya': 'gpt-4o-mini', 'wyy22': 'gpt-4o-mini'})
R.AFF_OVERRIDE = {'careke': 'aLn9', 'budsin': '069W', 'factory': '6oZK', 'chengmo': 'lz0Q'}
R.OUT = os.environ.get('OUTNAME', 'proxy100')

_orig_main = R.main
def main_paced():
    _orig_sleep = time.sleep
    def paced(n):
        _orig_sleep(max(n, 20))
    time.sleep = paced
    try:
        _orig_main()
    finally:
        time.sleep = _orig_sleep

if __name__ == '__main__':
    main_paced()
