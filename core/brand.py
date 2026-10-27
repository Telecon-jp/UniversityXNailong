"""校徽解析：从校徽图中提取品牌主色、辅助色与徽章裁切区域。

原理见 docs：白底 + 品牌色是校徽的典型结构，所以用色彩量化(k-means)
最稳。取每个簇的中位色而非聚类中心，避免抗锯齿边缘污染。
"""

from __future__ import annotations

import colorsys
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Brand:
    primary: str          # 主色 hex，如 #9B1B30
    secondary: str        # 辅助色 hex（无则等于主色）
    primary_ratio: float  # 主色在有效像素中的占比
    badge_bbox: list[int] # 校徽图形(非白)外接矩形 [x, y, w, h]
    source: str


def _load_rgba(path: Path) -> np.ndarray:
    """读图，返回 RGB 数组；透明像素用白色合成（校徽底通常是白的）。"""
    raw = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError(f"无法读取图片: {path}")
    if raw.ndim == 2:
        raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGRA)
    if raw.shape[2] == 4:
        b, g, r, a = cv2.split(raw)
        a3 = (a.astype(np.float32) / 255.0)[..., None]
        rgb = np.concatenate([r[..., None], g[..., None], b[..., None]], axis=2).astype(np.float32)
        rgb = rgb * a3 + 255.0 * (1.0 - a3)   # 透明 -> 白
        return np.clip(rgb, 0, 255).astype(np.uint8)
    return cv2.cvtColor(raw[:, :, :3], cv2.COLOR_BGR2RGB)


def _to_hex(rgb) -> str:
    r, g, b = (int(round(v)) for v in rgb[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def _shrink(img: np.ndarray, long_side: int = 240) -> np.ndarray:
    h, w = img.shape[:2]
    s = long_side / max(h, w)
    if s >= 1:
        return img
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)


def _is_background(pixel_rgb) -> bool:
    """判定是否为白/近白/低饱和浅色背景。"""
    r, g, b = [v / 255.0 for v in pixel_rgb[:3]]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return s < 0.10 and v > 0.80


def _load_rgb_alpha(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """读图，返回 (rgb, alpha)。alpha 为 None 表示原图不带透明通道。

    rgb 已把透明像素用白色合成，便于后续按"白底"处理；
    alpha 单独返回，用于识别"白色/浅色图形 + 透明背景"这类校徽。
    """
    raw = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError(f"无法读取图片: {path}（可能是损坏文件或非图片格式）")
    if raw.ndim == 2:
        raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGRA)

    alpha = None
    if raw.shape[2] == 4:
        b, g, r, a = cv2.split(raw)
        alpha = a
        a3 = (a.astype(np.float32) / 255.0)[..., None]
        rgb = np.concatenate([r[..., None], g[..., None], b[..., None]], axis=2).astype(np.float32)
        rgb = rgb * a3 + 255.0 * (1.0 - a3)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        return rgb, alpha
    rgb = cv2.cvtColor(raw[:, :, :3], cv2.COLOR_BGR2RGB)
    return rgb, alpha


def _shape_mask(rgb: np.ndarray, alpha: np.ndarray | None) -> np.ndarray:
    """求"校徽图形"区域，逐级放宽条件，尽量避免空结果。"""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    s = hsv[:, :, 1].astype(np.float32) / 255.0
    v = hsv[:, :, 2].astype(np.float32) / 255.0

    # 1) 原图带透明通道且确有透明区域 -> 直接用 alpha 当图形区域
    #    这样能处理"白色/浅色图形 + 透明底"的校徽
    if alpha is not None and float((alpha < 240).mean()) > 0.02:
        m = (alpha > 24).astype(np.uint8)
        if m.sum() > 50:
            return m

    # 2) 非白像素（常规白底校徽）
    for s_thr, v_thr in ((0.15, 0.75), (0.10, 0.85), (0.06, 0.92)):
        m = ((s > s_thr) | (v < v_thr)).astype(np.uint8)
        k = np.ones((3, 3), np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=2)
        if m.sum() > max(50, rgb.shape[0] * rgb.shape[1] * 0.001):
            return m

    # 3) 兜底：整张图都当作图形，靠聚类找主色
    return np.ones(rgb.shape[:2], np.uint8)


def total_n(clusters) -> int:
    return sum(c["n"] for c in clusters) or 1


def parse_brand(path: str | Path, k: int = 5) -> Brand:
    p = Path(path)
    rgb, alpha = _load_rgb_alpha(p)

    mask = _shape_mask(rgb, alpha)
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise ValueError(f"校徽中没有找到有效图形: {p.name}")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bbox = [int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)]

    # ---- 缩小后做 k-means，取品牌色 ----
    small = _shrink(rgb)
    small_mask = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    data = small.reshape(-1, 3)[small_mask.reshape(-1) > 0]
    if len(data) < 16:
        data = small.reshape(-1, 3)

    # k 自适应：样本太少时降低聚类数，避免 OpenCV 报错
    k_use = int(max(2, min(k, max(2, len(data) // 64))))

    data_f = np.ascontiguousarray(data.astype(np.float32))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, _ = cv2.kmeans(data_f, k_use, None, criteria, 5, cv2.KMEANS_PP_CENTERS)

    clusters = []
    for ci in range(k_use):
        member = data[labels.reshape(-1) == ci]
        if len(member) == 0:
            continue
        med = np.median(member, axis=0)
        r_, g_, b_ = [v / 255.0 for v in med[:3]]
        _, sat, val = colorsys.rgb_to_hsv(r_, g_, b_)
        # 饱和度越高、越"有颜色"，越像品牌色
        score = sat * (1.0 - abs(val - 0.45) * 0.8)
        clusters.append({"n": int(len(member)), "med": med, "sat": sat,
                         "val": val, "bg": _is_background(med), "score": score})

    if not clusters:
        raise ValueError(f"无法从校徽中提取颜色: {p.name}")

    # 优先在"非背景"簇里挑面积最大的；若都为背景（浅色校徽），
    # 则退而挑饱和度最高的那个，保证不会直接失败。
    useful = [c for c in clusters if not c["bg"]]
    if useful:
        useful.sort(key=lambda c: c["n"], reverse=True)
        primary = useful[0]
    else:
        clusters.sort(key=lambda c: c["score"], reverse=True)
        primary = clusters[0]

    # ---- 可用性校验：品牌色不能是纯白/纯灰，否则换色没有意义 ----
    def _usable(c) -> bool:
        return not (c["sat"] < 0.12 and c["val"] > 0.90)   # 不是近白

    if not _usable(primary):
        alt = [c for c in clusters if _usable(c)]
        if alt:
            alt.sort(key=lambda c: c["sat"] * 0.7 + c["n"] / max(total_n(clusters), 1) * 0.3,
                     reverse=True)
            primary = alt[0]
        else:
            raise ValueError(
                "这张校徽几乎是纯白/纯灰的，识别不出可用的品牌色。"
                "请上传带颜色的校徽图片（例如深色的校徽线条或彩色底）"
            )

    total = sum(c["n"] for c in clusters) or 1
    others = [c for c in clusters if c is not primary]
    secondary = others[0]["med"] if others else primary["med"]

    return Brand(
        primary=_to_hex(primary["med"]),
        secondary=_to_hex(secondary),
        primary_ratio=round(primary["n"] / total, 4),
        badge_bbox=bbox,
        source=str(p),
    )


def make_badge(path: str | Path, brand: Brand, pad_ratio: float = 0.02) -> "object":
    """裁出圆形徽章，圆外透明、圆内（含白盘）完整保留。

    注意：不能把圆内的白色当背景挖掉。校徽是"白盘+彩色图形"的整体，
    白盘是徽章的一部分，挖掉就只剩几根飘着的线了。
    """
    from PIL import Image, ImageDraw

    p = Path(path)
    rgb = _load_rgba(p)
    h, w = rgb.shape[:2]
    bx, by, bw, bh = brand.badge_bbox
    pad = int(round(max(bw, bh) * pad_ratio))
    x0 = max(0, bx - pad); y0 = max(0, by - pad)
    x1 = min(w, bx + bw + pad); y1 = min(h, by + bh + pad)
    crop = rgb[y0:y1, x0:x1]

    im = Image.fromarray(crop).convert("RGBA")

    # 方形化：以最长边为准，居中补白
    side = max(im.width, im.height)
    square = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    square.paste(im, ((side - im.width) // 2, (side - im.height) // 2))

    # 圆形遮罩：圆内全保留，圆外透明，边缘抗锯齿
    scale = 4
    mask = Image.new("L", (side * scale, side * scale), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, side * scale - 1, side * scale - 1), fill=255)
    mask = mask.resize((side, side), Image.LANCZOS)

    out = square.copy()
    out.putalpha(mask)
    return out


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "效果事例/OIP-C.webp"
    b = parse_brand(src)
    print(json.dumps(asdict(b), ensure_ascii=False, indent=2))
