"""按出处整理原始素材 -> E:\\vibeCoding\\奶龙生成\\原始素材\\<出处>\\

AB 两组：A 是最终采用的 18 张（来自奶蛙宇宙 / Nailong-Studio），
B 是前期调研时下载的其它站点素材（未采用），按来源分文件夹并保留下载清单。
"""
import json, os, shutil, hashlib
from PIL import Image

ROOT = r'E:\vibeCoding\奶龙生成'
RAW = os.path.join(ROOT, 'naiwa_raw')
OUT = os.path.join(ROOT, '原始素材')
CUT = os.path.join(ROOT, '奶蛙表情包')
manifest = json.load(open(os.path.join(CUT, 'manifest.json'), encoding='utf-8'))


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def info(src, dst):
    im = Image.open(src)
    w, h = im.size
    return dict(size=f'{w}x{h}', format=(im.format or '').upper(),
                frames=getattr(im, 'n_frames', 1), bytes=os.path.getsize(src),
                sha256=sha(src)[:16], saved_as=dst)


# ---------------- A) 采用素材：奶蛙宇宙（原始出处 Nailong-Studio） ----------------
A = os.path.join(OUT, '01_奶蛙宇宙_Nailong-Studio_采用素材')
os.makedirs(A, exist_ok=True)
rows = []
for e in manifest:
    rel = e['image_url'].split('.cn/')[-1]
    src = os.path.join(RAW, 'naiwa_universe', rel.replace('/', os.sep))
    dst_name = f"{e['file'].replace('.png', '')}{os.path.splitext(rel)[1]}"
    shutil.copy2(src, os.path.join(A, dst_name))
    rows.append(dict(cutout=e['file'], title=e['title'], category=e['category'],
                     site_id=e['id'], original_page=e['source'], author=e['author'],
                     license=e['license'], image_url=e['image_url'], **info(src, dst_name)))

json.dump(rows, open(os.path.join(A, '_来源清单.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)

# 站点的完整目录（74 条），说明只取了其中 18 条
shutil.copy2(os.path.join(RAW, 'naiwa_universe', 'catalog.json'),
             os.path.join(A, '_站点完整目录_catalog全部74条.json'))
cat = json.load(open(os.path.join(RAW, 'naiwa_universe', 'catalog.json'), encoding='utf-8'))
used = {e['id'] for e in manifest}

md = ['# 采用素材 · 奶蛙宇宙 / Nailong-Studio', '',
      f'- 收录站点：<a href="https://xn--yusy1ctb971x.cn/memes.html">奶蛙宇宙（非官方爱好者站）</a>',
      '- 站点数据接口：`https://xn--yusy1ctb971x.cn/api/catalog`（已存为 `_站点完整目录_catalog全部74条.json`，共 74 条）',
      '- 素材原始出处：Nailong-Studio，逐张链接见下表 `原始页面`',
      '- 授权：源仓库 MIT；角色权利归原权利人。仅作内部测试用图，勿商用/二次分发', '',
      f'本文件夹收录 **{len(rows)}** 张原始素材（即成品目录里 18 张抠图的原图），文件名前缀与成品一一对应。', '',
      '| 成品 | 原图文件 | 标题 | 站点ID | 原始页面 | 尺寸 | 帧 | 体积 |',
      '| --- | --- | --- | --- | --- | --- | --- | --- |']
for r in rows:
    md.append(f"| `{r['cutout']}` | `{r['saved_as']}` | {r['title']} | {r['site_id']} | "
              f"[原页]({r['original_page']}) | {r['size']} | {r['frames']} | {r['bytes'] // 1024} KB |")
md += ['', '> `_站点完整目录_catalog全部74条.json` 是站点全部 74 条表情的原始元数据，',
       '> 其中未被本轮采用的 56 条没有下载图片，如需可随时按其中的 `image` 字段补齐。', '']
open(os.path.join(A, 'README.md'), 'w', encoding='utf-8').write('\n'.join(md))
print('A done', len(rows))

# ---------------- B) 未采用的调研素材 ----------------
B = {
    'github_naiwa': ('02_Nailong-Studio_GitHub_奶蛙桌宠', 'https://github.com/tzshuai07/naiwa',
                     '奶蛙桌宠项目（MIT）。32 帧采样动画 webp，原始帧 643x824、自带透明通道，已去白边；未采用：只是同一只奶蛙的动画帧，表情不如成品丰富'),
    'neta': ('03_neta.art_奶蛙头像库', 'https://neta.art/app/milk-frog-avatar-wallpaper',
             'Neta Studio 的奶蛙头像库/素材页。48 张 512x512 扁平头像 + 官方三视图 + 印样表；未采用：扁平矢量风格，与本次实拍风表情包不一致，但很适合当识别训练的反例/多风格数据'),
    'qiubiaoqing': ('04_求表情网_奶蛙表情包', 'https://www.qiubiaoqing.com/album/user_album/948914371940058203.html',
                    '求表情网上的奶蛙实拍 GIF 表情包（240x240 左右，带站点水印、背景为主观场景）；未采用：分辨率低且带水印，抠图不可靠'),
    'cand2': ('04_求表情网_奶蛙表情包/_候选', 'https://www.qiubiaoqing.com',
              '从多个奶蛙合辑里筛出的候选 GIF/JPG，供参考；未采用同上'),
    'naiwa_universe': ('01_奶蛙宇宙_Nailong-Studio_采用素材/_站点页面', 'https://xn--yusy1ctb971x.cn/',
                       '站点页面/脚本原样存档，便于复核来源'),
}
for key, (folder, page, note) in B.items():
    s = os.path.join(RAW, key)
    if not os.path.isdir(s):
        continue
    d = os.path.join(OUT, folder.replace('/', os.sep))
    os.makedirs(d, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(s)):
        sp = os.path.join(s, f)
        if os.path.isfile(sp):
            shutil.copy2(sp, os.path.join(d, f))
            n += 1
    open(os.path.join(d, '_来源说明.txt'), 'w', encoding='utf-8').write(
        f'来源站点：{page}\n出处说明：{note}\n文件数：{n}\n')
    print('B', folder, n)

# 顶部索引
idx = ['# 原始素材索引', '',
       '本轮任务里下载过的全部原始素材，按出处分文件夹存放。成品抠图在 `../奶蛙表情包/`。', '',
       '| 文件夹 | 出处 | 用途 | 张数 |', '| --- | --- | --- | --- |',
       '| `01_奶蛙宇宙_Nailong-Studio_采用素材` | [奶蛙宇宙](https://xn--yusy1ctb971x.cn/memes.html) → Nailong-Studio | **18 张成品抠图的原始图** | 18 |',
       '| `02_Nailong-Studio_GitHub_奶蛙桌宠` | [tzshuai07/naiwa](https://github.com/tzshuai07/naiwa) | 调研备选，未采用 | 32 |',
       '| `03_neta.art_奶蛙头像库` | [neta.art](https://neta.art/app/milk-frog-avatar-wallpaper) | 调研备选（扁平风），未采用 | 62 |',
       '| `04_求表情网_奶蛙表情包` | [求表情网](https://www.qiubiaoqing.com/) | 最早尝试的素材，水印+杂背景，未采用 | 45 |',
       '', '每个文件夹内的 `_来源清单.json` / `README.md` / `_来源说明.txt` 记录了逐张出处、作者与授权。', '']
open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write('\n'.join(idx))
print('index done')
