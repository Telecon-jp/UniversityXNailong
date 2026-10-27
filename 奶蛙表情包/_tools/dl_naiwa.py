import json, os, urllib.request
import concurrent.futures as cf
BASE = 'https://xn--yusy1ctb971x.cn/'
HDR = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36',
       'Referer': BASE}
OUT = r'E:\vibeCoding\奶龙生成\naiwa_raw\naiwa_universe'
d = json.load(open(os.path.join(OUT, 'catalog.json'), encoding='utf-8'))
os.makedirs(os.path.join(OUT, 'assets'), exist_ok=True)
urls = sorted({m['image'] for m in d['memes']})


def grab(rel):
    dst = os.path.join(OUT, rel.replace('/', os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        r = urllib.request.urlopen(urllib.request.Request(BASE + rel, headers=HDR), timeout=60)
        data = r.read()
        open(dst, 'wb').write(data)
        return rel, r.status, len(data)
    except Exception as e:
        return rel, 'ERR', str(e)[:60]


with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(grab, urls))
for r in res:
    print(r)
print('ok', sum(1 for r in res if r[1] == 200), '/', len(res))
