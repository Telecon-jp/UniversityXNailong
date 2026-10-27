import os, sys
import numpy as np
from PIL import Image, ImageDraw

d = r'E:\vibeCoding\奶龙生成\奶蛙表情包'
fs = sorted(f for f in os.listdir(d) if f.endswith('.png'))
tiles = []
for f in fs:
    im = Image.open(os.path.join(d, f)).convert('RGBA')
    im.thumbnail((300, 300))
    w, h = im.size
    yy, xx = np.mgrid[0:h, 0:w]
    chk = np.where(((yy // 12 + xx // 12) % 2) == 0, 250, 200).astype(np.uint8)
    bg = Image.fromarray(np.dstack([chk, chk, chk]), 'RGB').convert('RGBA')
    bg.alpha_composite(im)
    t = bg.convert('RGB')
    fr = Image.new('RGB', (t.width + 4, t.height + 20), 'white')
    fr.paste(t, (2, 18))
    ImageDraw.Draw(fr).text((3, 3), f[:34], fill='black')
    tiles.append(fr)
cols = 5
W = max(t.width for t in tiles) + 4
H = max(t.height for t in tiles) + 4
rows = (len(tiles) + cols - 1) // cols
s = Image.new('RGB', (W * cols, H * rows), 'white')
for i, t in enumerate(tiles):
    s.paste(t, ((i % cols) * W, (i // cols) * H))
s.save(sys.argv[1] if len(sys.argv) > 1 else r'E:\vibeCoding\奶龙生成\_work\final_check.png')
print(s.size, len(fs))
