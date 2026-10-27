"""Final cut-out for 奶蛙 memes from 奶蛙宇宙 (xn--yusy1ctb971x.cn).

Backgrounds are clean (white / pale / green-screen), so the segmentation is
fully deterministic:
  1. estimate background colour from the frame border
  2. foreground = colour distance > thr   (+ soft alpha ramp for anti-aliasing)
  3. close small holes, keep the largest blobs only
  4. crop to content, pad, resize to a fixed square, save RGBA PNG
No per-image hand tuning: one threshold rule for the whole set.
"""
import json, os, sys
import numpy as np
from PIL import Image, ImageFilter

SRC = r'E:\vibeCoding\奶龙生成\naiwa_raw\naiwa_universe'
OUT = r'E:\vibeCoding\奶龙生成\奶蛙表情包'
SIZE = 768


def border_bg(rgb, w=10):
    f = rgb.astype(np.float32)
    px = np.concatenate([f[:w].reshape(-1, 3), f[-w:].reshape(-1, 3),
                         f[:, :w].reshape(-1, 3), f[:, -w:].reshape(-1, 3)])
    return np.median(px, axis=0)


def load_frame(path):
    im = Image.open(path)
    if getattr(im, 'n_frames', 1) == 1:
        return np.array(im.convert('RGB'))
    im.seek(getattr(im, 'n_frames', 1) // 2)
    return np.array(im.convert('RGB'))


def fill_holes(m):
    m = m.astype(np.uint8)
    bg = np.zeros_like(m)
    bg[0, :] = m[0, :] == 0
    bg[-1, :] = m[-1, :] == 0
    bg[:, 0] = m[:, 0] == 0
    bg[:, -1] = m[:, -1] == 0
    while True:
        g = bg.copy()
        g[1:, :] |= bg[:-1, :]
        g[:-1, :] |= bg[1:, :]
        g[:, 1:] |= bg[:, :-1]
        g[:, :-1] |= bg[:, 1:]
        g &= (m == 0)
        if np.array_equal(g, bg):
            return bg == 0
        bg = g


def largest_blobs(m, keep=1, min_frac=0.01):
    H, W = m.shape
    lab = np.zeros(m.shape, np.int32)
    cur = 0
    sizes = {}
    for y0, x0 in zip(*np.nonzero(m)):
        if lab[y0, x0]:
            continue
        cur += 1
        lab[y0, x0] = cur
        st = [(y0, x0)]
        n = 0
        while st:
            y, x = st.pop()
            n += 1
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and m[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = cur
                    st.append((yy, xx))
        sizes[cur] = n
    if not sizes:
        return m
    keep_ids = sorted(sizes, key=lambda k: -sizes[k])[:keep]
    return np.isin(lab, keep_ids)


def resolve_bg(rgb):
    """Background colour, picked by source type (not hand tuned per image).

    studio  : several border regions share one colour -> that colour is the backdrop
    vignette: no shared colour -> lit studio wall, take the *lightest* border region
    green   : green-screen
    """
    f = rgb.astype(np.float32)
    h, w = rgb.shape[:2]
    ch, cw = h // 6, w // 6
    regions = []
    for ry in (0, h // 2 - ch // 2, h - ch):
        for rx in (0, w // 2 - cw // 2, w - cw):
            regions.append(np.median(f[ry:ry + ch, rx:rx + cw].reshape(-1, 3), axis=0))
    regions = np.array(regions)
    r, g, b = regions[0]
    if g > 120 and r < 0.55 * g and b < 0.55 * g:
        return regions[0], 'green'
    # how many border regions agree with each region (within 22 levels)
    agree = (np.sqrt(((regions[:, None, :] - regions[None, :, :]) ** 2).sum(axis=2)) < 22).sum(axis=1)
    if agree.max() >= 3:
        best = int(np.argmax(agree))
        return regions[best], 'studio'
    light = regions[np.argmax(regions.sum(axis=1))]
    return light, 'vignette'


def erode_mask(m, r=1):
    img = Image.fromarray((m.astype(np.uint8) * 255), 'L').filter(ImageFilter.MinFilter(2 * r + 1))
    return np.array(img) > 127


def flood_from_border(cand):
    """Background-like pixels reachable from the image border (scanline flood)."""
    m = cand.astype(np.uint8)
    seed = np.zeros_like(m)
    seed[0, :] = m[0, :]
    seed[-1, :] = m[-1, :]
    seed[:, 0] = m[:, 0]
    seed[:, -1] = m[:, -1]
    while True:
        g = seed.copy()
        g[1:, :] |= seed[:-1, :]
        g[:-1, :] |= seed[1:, :]
        g[:, 1:] |= seed[:, :-1]
        g[:, :-1] |= seed[:, 1:]
        g &= m
        if np.array_equal(g, seed):
            return seed.astype(bool)
        seed = g


def cut(path):
    rgb = load_frame(path)
    bg, kind = resolve_bg(rgb)
    f = rgb.astype(np.float32)
    dist = np.sqrt(((f - bg) ** 2).sum(axis=2))
    bg_thr = 46 if kind == 'vignette' else 30
    bgmask = flood_from_border(dist < bg_thr)
    fg = fill_holes(~bgmask)                 # character = everything the backdrop cannot reach
    fg = largest_blobs(fg, keep=1, min_frac=0.01)
    fg = fill_holes(fg)
    # soft alpha from colour distance, only inside the backdrop reachability —
    # this is what removes the thin dark contour line around studio renders
    ramp = np.clip((dist - (bg_thr * 0.75)) / (bg_thr * 1.4), 0, 1)
    alpha = np.where(fg, 1.0, np.where(bgmask, ramp * 0.9, ramp))
    alpha = np.maximum(alpha, np.where(fg, 1.0, 0.0))
    # keep the character edge slightly inset so dark rim pixels become transparent
    inner = erode_mask(fg, 1)
    alpha = np.where(inner, 1.0, np.minimum(alpha, np.where(fg, ramp, alpha)))
    if kind == 'green':                      # de-spill green on the rim
        r_, g_, b_ = f[..., 0], f[..., 1], f[..., 2]
        spill = (g_ > r_ + 12) & (g_ > b_ + 12)
        f[..., 1] = np.where(spill, 0.5 * (r_ + b_), g_)
        rgb = np.clip(f, 0, 255).astype(np.uint8)
    rgb2 = rgb
    a = Image.fromarray((np.clip(alpha, 0, 1) * 255).astype(np.uint8), 'L')
    a = a.filter(ImageFilter.GaussianBlur(0.7))
    a = np.array(a).astype(np.float32) / 255.0
    rgba = np.dstack([rgb2, (a * 255).astype(np.uint8)])
    ys, xs = np.nonzero(a > 0.06)
    if len(ys) == 0:
        raise RuntimeError('empty mask ' + path)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop = rgba[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    side = max(h, w)
    canvas = np.zeros((side, side, 4), np.uint8)
    canvas[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = crop
    img = Image.fromarray(canvas, 'RGBA').resize((SIZE, SIZE), Image.LANCZOS)
    return img, dict(crop=f'{w}x{h}', bg=[int(v) for v in bg], bg_kind=kind)


if __name__ == '__main__':
    cat = json.load(open(os.path.join(SRC, 'catalog.json'), encoding='utf-8'))
    sel = json.load(open(sys.argv[1], encoding='utf-8'))
    by_id = {m['id']: m for m in cat['memes']}
    os.makedirs(OUT, exist_ok=True)
    manifest = []
    for i, item in enumerate(sel, 1):
        mid = item['id']
        meta = by_id[mid]
        src = os.path.join(SRC, meta['image'].replace('/', os.sep))
        safe = mid.replace('NW-', '').replace('-', '_')
        name = f'{i:02d}_{safe}_{item["slug"]}.png'
        img, info = cut(src)
        img.save(os.path.join(OUT, name))
        manifest.append(dict(file=name, id=mid, title=meta['title'], category=meta['category'],
                             source_format=meta['format'], source=meta['source'],
                             author=meta['author'], license=meta['license'],
                             origin='https://xn--yusy1ctb971x.cn/memes.html',
                             image_url='https://xn--yusy1ctb971x.cn/' + meta['image'],
                             **info))
        print('ok', name, info['crop'])
    json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
