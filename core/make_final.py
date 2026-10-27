"""出成品：跑全套，自动质检，输出一套可用的成品展示。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))

from brand import parse_brand, _load_rgba          # noqa: E402
from recolor import RenderConfig, build_masks, render, cfg_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "奶蛙表情包"
LOGO = ROOT / "效果事例" / "事例1" / "OIP-C.webp"
OUT = ROOT / "output" / "final"
OUT.mkdir(parents=True, exist_ok=True)

CFG = RenderConfig(l_shift_strength=0.95)


def quality(result: np.ndarray, masks, brand) -> dict:
    """客观质检：颜色是否到位、徽章是否合理落位。"""
    q = {}
    body = masks["body_only"] > 0.5
    if body.sum() < 200:
        return {"pass": False, "why": "主体过小"}

    hsv = cv2.cvtColor(result, cv2.COLOR_RGB2HSV)
    H = hsv[:, :, 0][body].astype(np.float32) * 2.0
    S = hsv[:, :, 1][body].astype(np.float32) / 255.0

    from recolor import hex_to_hsl
    th, ts, _ = hex_to_hsl(brand.primary)
    dh = float(np.median(np.abs(((H - th + 180) % 360) - 180)))
    q["hue_dev"] = round(dh, 1)
    q["sat"] = round(float(np.median(S)), 2)

    # 徽章是否落在身体内：检查图像底边附近有没有徽章（掉出画面的迹象）
    # 用徽章引入的改动量在图像下半部与整体之比衡量
    q["belly_ok"] = float((masks["belly"] > 0.5).mean()) > 0.004

    reasons = []
    if dh > 20:
        reasons.append(f"色相偏差{dh:.0f}°")
    if not q["belly_ok"]:
        reasons.append("无白肚皮(定位不可靠)")
    q["pass"] = not reasons
    q["why"] = "；".join(reasons)
    return q


def main():
    brand = parse_brand(LOGO)
    files = sorted(p for p in PACK.glob("*.png") if p.name != "preview.png")
    print(f"共 {len(files)} 张，校徽 {brand.primary}\n")

    good, bad = [], []
    for p in files:
        try:
            cfg = cfg_for(p, RenderConfig(l_shift_strength=0.95))
            result, _, masks = render(p, brand, LOGO, cfg)
            q = quality(result, masks, brand)
            Image.fromarray(result).save(OUT / p.name)
            q["file"] = p.name
            (good if q["pass"] else bad).append(q)
            mark = "OK  " if q["pass"] else "SKIP"
            print(f"{mark} {p.name:40s} 色相{q['hue_dev']:5.1f}° 饱和{q['sat']:.2f} "
                  + (q["why"] if q["why"] else ""))
        except Exception as e:  # noqa: BLE001
            bad.append({"file": p.name, "pass": False, "why": f"异常:{e}"})
            print(f"ERR  {p.name:40s} {e}")

    print(f"\n成品 {len(good)} 张 / 跳过 {len(bad)} 张")
    (OUT / "_quality.json").write_text(
        json.dumps({"good": good, "bad": bad}, ensure_ascii=False, indent=2), encoding="utf-8")

    make_sheet(good, OUT / "_final_sheet.png")


def make_sheet(good, path, cell=260, cols=4):
    """原图 | 成品 并排展示。"""
    rows = (len(good) + cols - 1) // cols
    pad = 12
    head = 52
    W = cols * (cell * 2 + pad) + pad
    H = head + rows * (cell + pad) + pad
    sheet = Image.new("RGB", (W, H), (247, 247, 250))
    d = ImageDraw.Draw(sheet)
    d.rectangle([0, 0, W, head], fill=(32, 32, 40))
    d.text((16, 18), f"奶蛙 x 校徽  成品 {len(good)} 张   左:原图  右:成品", fill=(255, 255, 255))

    for i, q in enumerate(good):
        cx = pad + (i % cols) * (cell * 2 + pad)
        cy = head + (i // cols) * (cell + pad)
        o = Image.open(PACK / q["file"]).convert("RGBA")
        o.thumbnail((cell, cell), Image.LANCZOS)
        bg = Image.new("RGB", (cell, cell), (255, 255, 255))
        bg.paste(o, ((cell - o.width) // 2, (cell - o.height) // 2), o)
        sheet.paste(bg, (cx, cy))
        d.rectangle([cx, cy, cx + cell - 1, cy + cell - 1], outline=(215, 215, 222))

        n = Image.open(OUT / q["file"]).convert("RGBA")
        n.thumbnail((cell, cell), Image.LANCZOS)
        bg2 = Image.new("RGB", (cell, cell), (255, 255, 255))
        bg2.paste(n, ((cell - n.width) // 2, (cell - n.height) // 2), n)
        sheet.paste(bg2, (cx + cell + 2, cy))
        d.rectangle([cx + cell + 2, cy, cx + cell * 2 + 1, cy + cell - 1], outline=(215, 215, 222))

    sheet.save(path)
    print("展示图:", path)


if __name__ == "__main__":
    main()
