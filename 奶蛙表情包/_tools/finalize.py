"""生成交付物：preview.png（预览）+ 重写 manifest + README。"""

import json, os
import numpy as np
from PIL import Image, ImageDraw
try:
    from PIL import ImageFont
    FONT = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 15)
except Exception:                                    # font missing -> default bitmap font
    FONT = None

OUT = r'E:\vibeCoding\奶龙生成\奶蛙表情包'
SITE = 'https://xn--yusy1ctb971x.cn/memes.html'
manifest = json.load(open(os.path.join(OUT, 'manifest.json'), encoding='utf-8'))

# ---------- preview sheet ----------
cell, pad, label_h = 260, 10, 22
cols = 5
rows = (len(manifest) + cols - 1) // cols
W = cols * (cell + pad) + pad
H = rows * (cell + label_h + pad) + pad
sheet = Image.new('RGB', (W, H), (246, 246, 248))
draw = ImageDraw.Draw(sheet)
yy, xx = np.mgrid[0:cell, 0:cell]
checker = np.where(((yy // 10 + xx // 10) % 2) == 0, 255, 226).astype(np.uint8)
chk = Image.fromarray(np.dstack([checker] * 3), 'RGB').convert('RGBA')
for i, e in enumerate(manifest):
    r, c = divmod(i, cols)
    x = pad + c * (cell + pad)
    y = pad + r * (cell + label_h + pad)
    im = Image.open(os.path.join(OUT, e['file'])).convert('RGBA').resize((cell, cell), Image.LANCZOS)
    tile = chk.copy()
    tile.alpha_composite(im)
    sheet.paste(tile.convert('RGB'), (x, y + label_h))
    draw.text((x + 2, y + 4), f"{i + 1:02d} {e['title']}", fill=(20, 20, 20), font=FONT)
sheet.save(os.path.join(OUT, 'preview.png'))
print('preview', sheet.size)

# ---------- manifest with source + cut info ----------
for e in manifest:
    if 'origin' not in e:                        # idempotent: only enrich once
        e['output'] = {'size': '768x768', 'mode': 'RGBA', 'format': 'PNG',
                       'background': 'transparent', 'content_crop_px': e.pop('crop')}
        e['cutout'] = {'method': 'border-flood matting + distance ramp alpha + 0.7px feather',
                       'background_type': e.pop('bg_kind'), 'estimated_bg_rgb': e.pop('bg')}
        e['origin'] = SITE
json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)

# ---------- README ----------
lines = [
    '# 奶蛙表情包（已抠图）', '',
    f'共 **{len(manifest)}** 张，全部为 768×768 透明背景 PNG，画面里只有奶蛙角色本身，没有底图、水印或文字。', '',
    '## 文件说明', '',
    '| 文件 | 说明 |', '| --- | --- |',
    '| `NN_*.png` | 抠图成品，RGBA，透明底 |',
    '| `preview.png` | 全部表情的预览拼图（棋盘格底，可直观看透明区域） |',
    '| `manifest.json` | 每张图的标题、原始出处、作者、授权、抠图参数 |',
    '', '## 清单', '',
    '| # | 文件 | 表情 | 原始出处 |', '| --- | --- | --- | --- |',
]
for i, e in enumerate(manifest, 1):
    lines.append(f"| {i} | `{e['file']}` | {e['title']} | [原图]({e['image_url']}) |")
lines += [
    '', '## 来源与授权', '',
    f'- 素材来自 [奶蛙宇宙]({SITE})（非官方爱好者站）收录的奶蛙表情包，单张原始出处见 `manifest.json` 中的 `source` 字段。',
    '- 原站标注授权为「源仓库 MIT；角色权利归原权利人」，本项目仅作内部图像处理测试用图，请勿商用或二次分发。',
    '', '## 抠图做法', '',
    '1. 从画面边框估计背景色（区分白棚拍、灰棚拍、绿幕三种源）；',
    '2. 以该颜色为基准，从边框做连通泛洪，得到"背景可达区域"，其余即角色主体；',
    '3. 用颜色距离生成半透明软边（抗锯齿），绿幕图额外做绿色溢色抑制；',
    '4. 0.7px 高斯羽化，裁到内容外接框，居中放入 768×768 透明画布。',
    '', '对应脚本：`_tools/make_cutouts.py`（`selection.json` 为选图清单）。',
]
open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write('\n'.join(lines))
print('README ok')
