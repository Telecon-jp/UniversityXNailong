"""奶蛙换色与徽章贴合的核心渲染。

原理：
1. 只替换"色相+饱和度"，保留并重新映射"明度" -> 形体光影不丢
2. 按 HSV 规则分区，身体换色、肚皮/手掌/背景不动
3. 徽章用正片叠底融合，让它嵌进身体的明暗结构里
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from brand import Brand, make_badge, _load_rgba


@dataclass
class RenderConfig:
    # 换色强度 0~1，1 表示完全替换为新色相
    recolor_strength: float = 1.0
    # 保留肚皮（米白区域）不与身体同色
    keep_belly: bool = True
    # 肚皮被染色程度 0~1（keep_belly=False 时生效）
    belly_tint: float = 0.25
    # 徽章直径 = 肚皮短边 × 本系数。
    # 1.0 = 刚好贴住肚皮上下沿；1.5 = 填满白肚皮（左右不再留白边），
    # 超出的部分由"遮挡回填"裁掉，所以偏大是安全的。
    badge_scale: float = 1.50
    # 椭圆徽章：白肚皮是扁椭圆，圆形贴上去左右必然留白。
    # 开启后把校徽按肚皮比例压成椭圆，贴合度显著提高。
    badge_ellipse: bool = True
    # 椭圆徽章填充肚皮的比例（宽/高分别控制）
    badge_fill_x: float = 0.98
    badge_fill_y: float = 0.98
    # 徽章在胸口的垂直偏移，相对肚皮高度：0.5=肚皮正中，>0.5 往下
    badge_cy: float = 0.58
    # 徽章横向位置（0.5 = 肚皮水平居中）
    badge_cx: float = 0.50
    # 徽章贴上去的明暗融合强度
    blend_strength: float = 0.85
    # 圆柱弧度压暗强度
    badge_curve: float = 0.30
    # 球面隆起强度 0~1：越大，徽章越像贴在鼓起的肚皮曲面上（0=平面贴纸）
    badge_bulge: float = 0.85
    # 徽章边缘羽化半径（相对徽章尺寸的比例）
    badge_feather: float = 0.035
    # 超采样倍率：内存足够时 4 倍能让校徽文字明显更锐利
    badge_supersample: int = 4
    # 把手部重新叠回徽章之上，形成"抱着校徽"的层次
    hands_over_badge: bool = True
    # 把横跨肚皮的手臂（黄色，非灰色手掌）重新叠回徽章之上。
    # 开启后徽章可以铺满整个肚皮，由手臂遮住其中一部分。
    arms_over_badge: bool = True
    # 手部叠加的虚化半径，让边缘与徽章自然融合
    hands_feather: float = 1.6
    # 换色后整体饱和度保持比例：1.0 = 完整使用校徽色的饱和度
    sat_keep: float = 1.0
    # 明度整体迁移强度 0~1：把原图明度中位数往目标色明度靠多少。
    # 0 = 完全沿用原图明度，1 = 完全对齐到目标色明度
    l_shift_strength: float = 0.55


# ---------------------------------------------------------------- 分区

def build_masks(rgb: np.ndarray):
    """返回 body / belly / hand / bg 四张 0~1 浮点遮罩。"""
    h, w = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    H = hsv[:, :, 0].astype(np.float32) * 2.0   # 0~360
    S = hsv[:, :, 1].astype(np.float32) / 255.0
    V = hsv[:, :, 2].astype(np.float32) / 255.0

    # --- 背景：从四边泛洪，连通浅色区域 ---
    light = ((S < 0.16) & (V > 0.80)).astype(np.uint8)
    ff = light.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    seed_points = []
    for x in range(w):
        seed_points += [(x, 0), (x, h - 1)]
    for y in range(h):
        seed_points += [(0, y), (w - 1, y)]
    for (sx, sy) in seed_points:
        if ff[sy, sx] == 1:
            cv2.floodFill(ff, mask, (sx, sy), 2)
    bg = (ff == 2).astype(np.float32)

    # --- 身体：黄色系，色相 30~70，饱和度高 ---
    yellow = ((H >= 28) & (H <= 72) & (S > 0.22) & (V > 0.25)).astype(np.float32)
    body = yellow * (1.0 - bg)

    # --- 肚皮：低饱和、较亮、且被身体包围 ---
    # 之前用固定阈值 (S<0.26 & V>0.62)，很多奶蛙的肚皮偏黄不够白，
    # 会一个像素都检不出来（09/11/13 号就是这种情况），
    # 导致徽章定位退化到不可靠的兜底分支。
    #
    # 改为自适应：肚皮是"身体内部那一块比周围更亮的低饱和区域"，
    # 阈值相对身体自身的亮度分布来定，而不是写死。
    body_core = (H >= 28) & (H <= 72) & (V > 0.25)
    body_v = V[body_core] if body_core.any() else V.ravel()
    body_s = S[body_core] if body_core.any() else S.ravel()
    v_med = float(np.median(body_v))
    s_med = float(np.median(body_s))
    # 肚皮：饱和度明显低于身体（相对判断，不写死）
    # 之前的固定阈值 (S<0.34 & V>0.79) 会把肚皮的阴影部分排除掉——
    # 实测 03 号肚皮下半部 S 升到 0.27~0.37、V 降到 0.71~0.78，
    # 结果遮罩只盖到肚皮中部，徽章填不满。
    s_thr = max(0.30, s_med * 0.72)
    belly_loose = (
        (S < s_thr)
        & (V > 0.60)
        & (H >= 10) & (H <= 90)
    ).astype(np.float32) * (1.0 - bg)
    # --- 手掌：低饱和、亮度中等（灰色）---
    hand = ((S < 0.26) & (V < 0.66)).astype(np.float32) * (1.0 - bg)

    # 闭运算把身体内部的洞补上（肚皮的洞要保留，所以先算肚皮）
    k3 = np.ones((3, 3), np.uint8)
    body_u8 = cv2.morphologyEx((body > 0.5).astype(np.uint8), cv2.MORPH_CLOSE, k3, iterations=3)
    body_u8 = cv2.morphologyEx(body_u8, cv2.MORPH_OPEN, k3, iterations=1)

    # 只保留最大连通域（奶蛙主体），丢掉零散黄色噪点
    n, lab, stats, _ = cv2.connectedComponentsWithStats(body_u8, 8)
    if n > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        body_u8 = (lab == biggest).astype(np.uint8)

    # 身体内部填充（填掉肚皮/手掌造成的洞），得到完整剪影
    sil = body_u8.copy()
    cnts, _ = cv2.findContours(sil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(sil)
    cv2.drawContours(filled, cnts, -1, 1, thickness=cv2.FILLED)

    belly = np.clip(belly_loose, 0, 1) * (filled > 0)
    hand = np.clip(hand, 0, 1) * (filled > 0)

    # --- 白肚皮精修：取最大连通块 + 排除头部高光 ---
    # 问题：脸部/头部的白色高光也会被误判为肚皮。
    # 例如 01 号图，肚皮检测从 y=86（头顶附近）就开始了，包围盒高度 443
    # 远大于宽度 260，明显是把脸的高光混进来了。
    #
    # 修法两步：
    #   1) 只保留最大连通块（手臂把肚皮切开时，取主体那块）
    #   2) 肚皮在躯干上，不在头部——把包围盒限制在身体下半部
    b_u8 = (belly > 0.5).astype(np.uint8)
    if b_u8.sum() > 50:
        nb, lb_, stb, _ = cv2.connectedComponentsWithStats(b_u8, 8)
        if nb > 1:
            big = 1 + int(np.argmax(stb[1:, cv2.CC_STAT_AREA]))
            # 主体块 + 与其相邻的那些碎块（手臂切开的两半要合并回来）
            keep = np.zeros(nb, np.uint8)
            keep[big] = 1
            main_box = stb[big]
            for ci in range(1, nb):
                if ci == big:
                    continue
                cx_i, cy_i = stb[ci, cv2.CC_STAT_LEFT], stb[ci, cv2.CC_STAT_TOP]
                # 离主体块够近、且面积不算太小 -> 视为同一块肚皮
                near = (abs(cx_i - main_box[cv2.CC_STAT_LEFT]) < main_box[cv2.CC_STAT_WIDTH]
                        and abs(cy_i - main_box[cv2.CC_STAT_TOP]) < main_box[cv2.CC_STAT_HEIGHT])
                if near and stb[ci, cv2.CC_STAT_AREA] > 200:
                    keep[ci] = 1
            belly = (keep[lb_] > 0).astype(np.float32)

        # 排除头部高光：身体剪影的上沿到"躯干起点"之间不算肚皮
        sy = np.where(filled.sum(axis=1) > 0)[0]
        if sy.size:
            top_y, bot_y = int(sy.min()), int(sy.max())
            body_h = max(1, bot_y - top_y)
            # 头部约占身体上部 35%，肚皮不可能从这里开始
            head_cut = top_y + int(body_h * 0.30)
            yy2 = np.arange(filled.shape[0], dtype=np.float32)[:, None]
            belly = belly * (yy2 >= head_cut)

    # 手部膨胀 + 暗色保护：手指之间的缝隙是细长暗条，介于手掌之间，
    # 按"亮度低 + 靠近手掌"判定为不该染的区域，避免缝隙被染红后手变糊。
    hand_u8 = (hand > 0.5).astype(np.uint8)
    hand_u8 = cv2.morphologyEx(hand_u8, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    hand_dil = cv2.dilate(hand_u8, np.ones((7, 7), np.uint8), iterations=2).astype(np.float32)
    # 手部包围盒内的深色细缝
    dark_slit = ((V < 0.42) & (S < 0.35)).astype(np.float32) * hand_dil
    hand_guard = np.clip(hand_u8.astype(np.float32) + dark_slit, 0, 1) * (filled > 0)

    # --- 嘴部保护：嘴腔和牙齿不该被染色 ---
    # 关键：必须先排除手部！手是深灰色，同样满足"暗+低饱和"，
    # 之前没排除导致手被当成嘴腔，进而让徽章定位把整片手区域误判成五官，
    # 一路把徽章推到脚底。
    not_hand = 1.0 - np.clip(hand_guard, 0, 1)
    # 嘴腔：很暗(V低)且饱和不高，且不在手部区域
    mouth_cavity = ((V < 0.45) & (S < 0.55)).astype(np.float32) * (filled > 0) * not_hand
    # 牙齿/高光：接近白且低饱和
    teeth = ((V > 0.82) & (S < 0.25)).astype(np.float32) * (filled > 0)
    # 关键：白肚皮同样是"高亮+低饱和"，会被误判成牙齿！
    # 这个误判会让"徽章避开五官"的逻辑把肚皮当成五官，
    # 一路把徽章往下推到画面外。必须把肚皮从五官遮罩里排除。
    teeth = teeth * (1.0 - np.clip(belly, 0, 1))
    # 只保留"位于身体上半部"的嘴腔（嘴不会长在腿上），进一步排除误判
    yy = np.arange(h, dtype=np.float32)[:, None]
    upper = (yy < h * 0.62).astype(np.float32)
    # --- 色相偏离保护：绿眼睛等非身体色区域保持原色 ---
    # 奶蛙身体是黄色（色相约 38~40），眼睛是绿色（色相约 96~100），
    # 相差 58°。之前的规则只看饱和度和亮度，把绿眼睛当成身体染成了红色。
    # 这里按"色相与身体主体色相差超过 45°"识别出来，保持原样。
    body_hue_med = float(np.median(H[body_core])) if body_core.any() else 40.0
    dh_body = np.abs(((H - body_hue_med + 180) % 360) - 180)
    hue_guard = ((dh_body > 45) & (S > 0.20) & (V > 0.12)).astype(np.float32) * (filled > 0)
    # 嘴腔/牙齿仍限制在身体上半部；色相偏离区（眼睛）不受这个限制
    feature_guard = np.clip(
        (mouth_cavity + teeth) * upper + hue_guard, 0, 1
    )
    # 去掉与手掌重叠的部分（手部已单独处理）
    feature_guard = feature_guard * (1 - hand_guard)

    # 羽化：让边缘过渡自然。
    #
    # 关键修正：羽化半径必须按图像尺寸自适应。
    # 之前的半径（1.2/3.0/2.0/1.5）是为 185px 小图调的，在 768px 大图上
    # 相对尺寸只有 1/4，过渡带窄到几乎等于硬边 —— 一缩放就变成颗粒噪点。
    # 现在以图像长边为基准，换算成与之前小图等效的相对半径。
    scale = max(h, w) / 185.0        # 相对基准图(185px)的放大倍数
    scale = float(np.clip(scale, 0.8, 6.0))

    def feather(m, r=2.0):
        return cv2.GaussianBlur(m.astype(np.float32), (0, 0), r * scale)

    body_m = feather((filled > 0).astype(np.float32), 1.2)
    body_m = np.clip(body_m, 0, 1)
    # 肚皮边缘羽化要更宽，否则染色区与肚皮之间出现硬边
    belly_f = feather(belly, 3.0)
    hand_f = feather(hand_guard, 2.0)
    feat_f = feather(feature_guard, 1.5)
    # 保留身体但排除肚皮/手掌/五官
    body_only = np.clip(body_m - belly_f * 0.98 - hand_f * 0.98 - feat_f * 0.98, 0, 1)

    # --- 填洞：补齐换色区内部的漏网像素 ---
    # 颜色规则难免漏掉一些像素（高光过渡、抗锯齿边、肤色不均），
    # 表现为成品上的脏斑点（红色里混着原色黄点）。
    # 做法：从换色区的连通块里，把被其包围的小空洞补进来，
    # 但严格排除肚皮/手/五官——这些是真该保留的区域，不能误补。
    solid = (body_only > 0.5).astype(np.uint8)
    # 提取外部背景：从图像四周泛洪，凡是能连到边缘的都不是"内部空洞"
    inv = (1 - solid).astype(np.uint8)
    ff2 = inv.copy()
    m2 = np.zeros((inv.shape[0] + 2, inv.shape[1] + 2), np.uint8)
    for xx in range(inv.shape[1]):
        for yy in (0, inv.shape[0] - 1):
            if ff2[yy, xx] == 1:
                cv2.floodFill(ff2, m2, (xx, yy), 2)
    for yy in range(inv.shape[0]):
        for xx in (0, inv.shape[1] - 1):
            if ff2[yy, xx] == 1:
                cv2.floodFill(ff2, m2, (xx, yy), 2)
    holes = (ff2 == 1).astype(np.uint8)     # 不与边界连通的非换色区 = 内部空洞

    # 只补"小洞"：大洞多半是肚皮/手这类真实区域，误补会毁掉它们
    n_lab, lab = cv2.connectedComponents(holes, connectivity=8)
    fill_u8 = np.zeros_like(holes)
    max_hole = max(64, int(body_only.size * 0.004))
    for li in range(1, n_lab):
        m = (lab == li)
        area = int(m.sum())
        if area <= max_hole:
            # 不能碰肚皮/手/五官：这些区域即便小也不补
            blocked = (belly_f > 0.3) | (hand_f > 0.3) | (feat_f > 0.3)
            if not np.any(m & blocked):
                fill_u8[m] = 1

    fill = feather(fill_u8.astype(np.float32), 1.0)
    return {
        "body": body_m,
        "body_only": body_only,
        "belly": belly_f,
        "hand": hand_f,
        "feature": feat_f,
        "fill": fill,
        "bg": bg,
        "silhouette": filled.astype(np.float32),
    }


# ---------------------------------------------------------------- 换色

def hex_to_hsl(hex_str: str):
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        hue = ((g - b) / d + (6 if g < b else 0)) / 6
    elif mx == g:
        hue = ((b - r) / d + 2) / 6
    else:
        hue = ((r - g) / d + 4) / 6
    return hue * 360, s, l


def recolor(rgb: np.ndarray, masks, brand: Brand, cfg: RenderConfig) -> np.ndarray:
    """核心换色：在 Lab 空间替换色相/饱和，明度直接沿用原图。

    这一版的设计原则（前两版的教训）：

    第一版按固定系数重造亮度（暗部=目标×0.42），在偏暗图上压出土褐色。
    第二版按原图亮度跨度重造曲线，跨度大的图上推到过曝、偏褐，跨度小的图发灰。
    两版的共同错误是：**试图重新构造明度**。

    但原图的明度就是光照结果，它本身是"正确"的。重新构造必然引入色偏。
    所以这一版改为：
      1. 明度（Lab 的 L 通道）完全沿用原图 —— 形体光影 100% 保真
      2. 只替换色相和饱和度（Lab 的 a/b 通道）—— 这是"换色"该做的事
      3. 只把明度的整体位置往目标色收一点（不压缩跨度），避免黄色换成红色后偏粉

    Lab 空间的好处：a/b 通道是感知上均匀的色度平面，
    在这上面做替换不会像 HSV 那样在低明度时色相漂移发褐。
    """
    f = rgb.astype(np.float32) / 255.0

    # --- 转 Lab（OpenCV 8bit Lab: L 0~255, a/b 0~255 偏移128） ---
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab[:, :, 0]                      # 0~255，即原图明度，绝不动它的结构

    # --- 目标色的 Lab 色度 ---
    target_rgb = np.uint8([[[
        int(brand.primary[1:3], 16),
        int(brand.primary[3:5], 16),
        int(brand.primary[5:7], 16),
    ]]])
    t_lab = cv2.cvtColor(target_rgb, cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
    t_L, t_a, t_b = float(t_lab[0]), float(t_lab[1]), float(t_lab[2])

    # --- 身体区域的明度分布 ---
    bm = masks["body_only"] > 0.5
    if bm.sum() < 100:
        bm = masks["body"] > 0.5
    src_L = L[bm] if bm.any() else L.ravel()

    # --- 明度处理：分位数映射（这个项目的关键一步） ---
    #
    # 为什么不能只平移：奶蛙是黄色，明度中位数约 168~189；
    # 校徽红是深红，明度中位数只有 81。只对齐中位数时整体仍偏高，成品发粉。
    # 根源是"红色物体在同样光照下本来就比黄色物体暗"——这是颜色本身的属性。
    #
    # 正确做法：把奶蛙的明度分布按分位数映射到"红色该有的分布"上。
    #   · 按分位数映射 => 原来亮的像素仍排在前面（相对明暗关系保住 => 立体感在）
    #   · 目标分布是深红区间 => 整体落在正确的明度上（颜色正)
    #
    # 目标分布怎么来：以校徽主色的 Lab 明度为锚点，构造一条红色的典型明度曲线。
    # 深红物体受光后，从暗部到高光大致覆盖 [目标L*0.6, 目标L*1.9] 这个范围。
    target_lo = max(6.0, t_L * 0.62)     # 暗部
    target_hi = min(250.0, t_L * 1.95)   # 高光（受光面会比本色亮不少）
    target_med = t_L                     # 中间调就是本色明度

    # 源分布的分位数锚点
    src_p05 = float(np.percentile(src_L, 5))
    src_p50 = float(np.percentile(src_L, 50))
    src_p95 = float(np.percentile(src_L, 95))

    # 分段线性分位数映射：p05->target_lo, p50->target_med, p95->target_hi
    # 单调性保证：亮的一定映射到更亮，暗的一定更暗
    def seg_map(x, a0, a1, a2, b0, b1, b2):
        lo = b0 + (b1 - b0) * (x - a0) / max(a1 - a0, 1e-3)
        hi = b1 + (b2 - b1) * (x - a1) / max(a2 - a1, 1e-3)
        return np.where(x <= a1, lo, hi)

    # 用 l_shift_strength 控制映射强度：0=完全沿用原图明度，1=完全映射到红色分布
    mapped = seg_map(L, src_p05, src_p50, src_p95, target_lo, target_med, target_hi)
    L_new = L * (1 - cfg.l_shift_strength) + mapped * cfg.l_shift_strength

    # 高光保护：接近白的像素（反光/油亮）不要被压暗，保住塑料质感
    hi_mask = np.clip((L - 0.90 * 255) / (0.10 * 255), 0, 1)
    L_new = L_new * (1 - hi_mask) + L * hi_mask
    L_new = np.clip(L_new, 0, 255)

    # --- 色度处理 ---
    # 之前的错误：基准色度再乘 0.85~1.15 的调制，最后实际饱和度只有目标色的 ~76%，
    # 成品因此"被冲淡"、看起来偏粉。校徽红是 S≈0.92 的极高饱和，必须给足。
    #
    # 现在：色度直接用目标色的完整强度，只叠加一点点由原图局部鲜艳度带来的变化
    # （用于保留明暗过渡的自然感），幅度控制在 ±6% 以内。
    orig_chroma = np.sqrt(lab[:, :, 1] ** 2 + lab[:, :, 2] ** 2)
    target_chroma = float(np.sqrt(t_a ** 2 + t_b ** 2))
    if target_chroma < 1e-3:
        target_chroma = 60.0
    # 目标色的色度方向
    dir_a, dir_b = t_a / target_chroma, t_b / target_chroma

    # 局部鲜艳度：相对身体区域中位数归一，只用来做 ±6% 的微调
    c_med = float(np.median(orig_chroma[bm])) if bm.any() else 1.0
    c_med = max(c_med, 1e-3)
    local = np.clip(orig_chroma / c_med, 0.4, 1.8)
    # 映射到 [0.94, 1.06] 的窄区间
    mod = 1.0 + (local - 1.0) * 0.07

    new_chroma = target_chroma * cfg.sat_keep * mod
    new_a = dir_a * new_chroma
    new_b = dir_b * new_chroma

    # --- 合成 ---
    lab_new = np.stack([L_new, new_a, new_b], axis=2)
    new_rgb = cv2.cvtColor(np.clip(lab_new, 0, 255).astype(np.uint8),
                           cv2.COLOR_LAB2RGB).astype(np.float32) / 255.0

    # 肚皮：保留原色，或轻微染色
    belly_m = masks["belly"][..., None]
    if cfg.keep_belly:
        belly_rgb = f
    else:
        belly_rgb = f * (1 - cfg.belly_tint) + new_rgb * cfg.belly_tint

    # 手掌保持
    hand_m = masks["hand"][..., None]
    # 五官内部保持原色（嘴腔、牙齿）
    feat_m = masks.get("feature")
    feat_m = feat_m[..., None] if feat_m is not None else np.zeros_like(hand_m)

    # 换色遮罩 = 身体（已排除肚皮/手/五官）+ 填洞补齐的漏网像素
    body_only = masks["body_only"]
    fill = masks.get("fill")
    if fill is not None:
        body_only = np.clip(body_only + fill, 0, 1)

    out = f.copy()
    body_m = body_only[..., None] * cfg.recolor_strength
    out = out * (1 - body_m) + new_rgb * body_m
    out = out * (1 - belly_m) + belly_rgb * belly_m
    out = out * (1 - hand_m) + f * hand_m
    out = out * (1 - feat_m) + f * feat_m
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


# ---------------------------------------------------------------- 徽章

def _blend_badge_on(out: np.ndarray, badge: Image.Image, masks_up, cfg: RenderConfig,
                    body_w: int, cx: int, cy: int, size_w: int, size_h: int | None = None) -> None:
    """在已放大的画布上把徽章贴到 (cx, cy)。

    size_w / size_h 分别控制宽高。两者不等时，徽章会被压成椭圆
    （圆形 alpha 经非等比缩放后自然变成椭圆），用来贴合扁椭圆形的白肚皮。
    """
    h, w = out.shape[:2]
    if size_h is None:
        size_h = size_w
    badge_r = badge.resize((max(2, size_w), max(2, size_h)), Image.LANCZOS)
    arr = np.array(badge_r, dtype=np.float32) / 255.0
    brgb, balpha = arr[..., :3], arr[..., 3:4]

    left, top = cx - size_w // 2, cy - size_h // 2
    x0, y0 = max(0, left), max(0, top)
    x1, y1 = min(w, left + size_w), min(h, top + size_h)
    if x1 <= x0 or y1 <= y0:
        return

    sx0, sy0 = x0 - left, y0 - top
    sub = out[y0:y1, x0:x1]
    sub_badge = brgb[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
    sub_alpha = balpha[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
    size = min(size_w, size_h)

    # ---- 球面隆起：用光影制造"鼓起来"的感觉 ----
    #
    # 我一度尝试几何变形（径向 remap）来模拟球面投影，结果把徽章压成了竖线。
    # 教训：几何变形容易出错且难以控制，而人眼判断"曲面"主要靠明暗——
    # 所以正确做法是只用光影：
    #   1. 中心亮、边缘暗（球面边缘背离视线）
    #   2. 上方略亮、下方略暗（光从上方来）
    #   3. 加一个高光点，强化"圆鼓鼓"的立体感
    yy, xx = np.mgrid[0:sub.shape[0], 0:sub.shape[1]]
    cx_b = (sub.shape[1] - 1) / 2.0
    cy_b = (sub.shape[0] - 1) / 2.0
    nx = (xx - cx_b) / max(1, sub.shape[1] / 2.0)
    ny = (yy - cy_b) / max(1, sub.shape[0] / 2.0)
    r_norm = np.sqrt(nx ** 2 + ny ** 2)

    # 基础球面衰减：中心 1.0，边缘 (1 - curve)
    shade = 1.0 - cfg.badge_curve * np.clip(r_norm ** 2, 0, 1)
    # 上方来光：ny 为负是上方，所以取 -ny
    shade = shade * (1.0 + 0.07 * np.clip(-ny, -1, 1))
    # 高光：左上方一个柔和亮斑，模拟球面反光
    if cfg.badge_bulge > 0:
        hx, hy = -0.30, -0.35          # 高光在左上
        d2 = (nx - hx) ** 2 + (ny - hy) ** 2
        spec = np.exp(-d2 / (2 * 0.22 ** 2)) * 0.28 * cfg.badge_bulge
        shade = shade + spec
    shade = np.clip(shade, 0, 1.6)[..., None]

    # 球面受光：中心亮、四周暗（球体贴在身体上，边缘背离视线方向）
    bulge_shade = 1.0 - cfg.badge_curve * np.clip(r_norm ** 2, 0, 1)
    # 上部略亮、下部略暗，模拟上方来光
    bulge_shade = bulge_shade * (1.0 + 0.06 * (-ny))
    shade = np.clip(bulge_shade, 0, 1)[..., None]

    # ---- 边缘羽化 ----
    # 直接在圆形 alpha 上做高斯模糊会向外渗到方形画布的角，形成可见方框。
    # 与原始 alpha 取 min，保证衰减只在圆内发生、绝不越出圆形边界。
    if cfg.badge_feather > 0:
        feather_r = max(0.6, size * cfg.badge_feather)
        blurred = cv2.GaussianBlur(sub_alpha[..., 0], (0, 0), feather_r)
        sub_alpha = np.minimum(blurred, sub_alpha[..., 0])[..., None]
    sub_alpha = np.clip(sub_alpha, 0, 1)

    # ---- 融合 ----
    # 校徽是"白盘 + 彩色图形"的整体：白盘也要显示，否则徽章会碎成几根飘线。
    # 但白盘要压成身体色调的浅色，线稿用徽章本色，两者明暗都跟随身体受光。
    sub_lum = (0.299 * sub_badge[..., 0] + 0.587 * sub_badge[..., 1] + 0.114 * sub_badge[..., 2])
    valid = sub_alpha[..., 0] > 0.5
    if valid.any():
        bmin = float(np.percentile(sub_lum[valid], 2))
        bmax = float(max(np.percentile(sub_lum[valid], 98), bmin + 1e-3))
    else:
        bmin, bmax = 0.2, 0.9

    # ink: 0 = 白盘, 1 = 彩色图形线条
    ink = np.clip(1.0 - (sub_lum - bmin) / (bmax - bmin), 0, 1)[..., None]

    body_lum = (0.299 * sub[..., 0] + 0.587 * sub[..., 1] + 0.114 * sub[..., 2])[..., None]

    # 白盘 -> 暖白，亮度随身体该处明暗（避免死白像贴纸）
    paper = np.clip(0.74 + 0.26 * body_lum, 0, 1) * np.array([1.0, 0.985, 0.955], np.float32)
    # 线稿 -> 徽章本色，明暗随身体受光
    ink_col = sub_badge * (0.66 + 0.34 * body_lum)

    blended = paper * (1 - ink) + ink_col * ink
    # 整体再乘一个受光因子，让徽章参与身体的体积感
    blended = blended * (0.84 + 0.16 * body_lum)

    blended = np.where(valid[..., None], blended, sub)
    blend = blended * cfg.blend_strength + sub * (1 - cfg.blend_strength)
    blend = np.where(valid[..., None], blend, sub)

    a = np.clip(sub_alpha * shade, 0, 1)
    out[y0:y1, x0:x1] = sub * (1 - a) + blend * a


def apply_badge(canvas: np.ndarray, badge: Image.Image, masks, cfg: RenderConfig,
                original: np.ndarray | None = None) -> np.ndarray:
    """把徽章贴到白肚皮上，采用超采样保证线条锐利。

    定位规则来自三组示例的实测共识：
      · 徽章直径 ≈ 肚皮宽度的 85%
      · 圆心 ≈ 肚皮水平中心，垂直略低于肚皮中心
      · 手部压在徽章之上（"抱着校徽"的层次）

    original 传入原始（换色前）图像，用于在徽章之上重建手部图层。
    """
    h, w = canvas.shape[:2]

    ys, xs = np.where(masks["silhouette"] > 0.5)
    if len(xs) == 0:
        return canvas
    bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
    body_w = bx1 - bx0

    # ---- 定位：优先以白肚皮为基准 ----
    # 注意：白肚皮常被手臂挡住一部分，可见区域的包围盒会偏斜，
    # 所以水平中心用"肚皮像素的中位数"更稳，尺寸用肚皮宽度。
    belly_ys, belly_xs = np.where(masks["belly"] > 0.5)
    occ_mask = None          # 遮挡区（手臂横跨肚皮的部分），由下面的分支填充
    belly_found = len(belly_xs) > 50
    if belly_found:
        bw = belly_xs.max() - belly_xs.min() + 1
        bh = belly_ys.max() - belly_ys.min() + 1
        # 圆心用肚皮的"质心"（而非包围盒比例）：扁椭圆肚皮上，
        # 质心才是能容纳最大内切圆的位置。
        cx = int(belly_xs.mean())
        cy = int(belly_ys.mean())
        # 允许用配置做细微偏移
        cx = int(cx + bw * (cfg.badge_cx - 0.5))
        cy = int(cy + bh * (cfg.badge_cy - 0.5))
        # ---- 肚皮几何：恢复"被手臂遮挡前的完整肚皮" ----
        # 02 号这种抱胸姿态，白肚皮被手臂切成上下两块（上小下大）。
        # 用户要的效果是：徽章覆盖整个肚皮，手臂压在上面遮住一部分。
        # 所以不能只用最大那块，而要把两块"补"成一个完整椭圆：
        #   · 用凸包把被手臂切开的缺口合上，得到完整肚皮形状
        #   · 缺口处（手臂）记为遮挡区，渲染后要把身体重新盖回徽章上
        bmask = (masks["belly"] > 0.5).astype(np.uint8)
        sil_bool = masks["silhouette"] > 0.5
        pts = np.column_stack(np.where(bmask > 0))          # (y,x)
        bmask_full = bmask.copy()

        # ---- 清理杂斑，并判断是否需要跨手臂补全 ----
        # 实测两种情形必须区别对待：
        #   · 01 号：白肚皮右侧有一块"手臂高光"被误判为肚皮，
        #     它把包围盒拉宽、把圆心拽右，导致徽章偏右且不准。
        #     这种"位于主体右侧/下方"的碎块应当丢弃。
        #   · 02 号：白肚皮被交叉手臂切成上下两块，
        #     上面那块是真实肚皮的一部分，应当合并（凸包补全）。
        # 判据：碎块在主体的"上方" => 被手臂切开，合并；否则 => 杂斑，丢弃。
        nc_b, lc_b, sc_b, ce_b = cv2.connectedComponentsWithStats(bmask, 8)
        if nc_b > 2:
            order = np.argsort(sc_b[1:, cv2.CC_STAT_AREA])[::-1] + 1
            main_id = int(order[0])
            m_y = float(ce_b[main_id][1])
            m_h = float(sc_b[main_id, cv2.CC_STAT_HEIGHT])
            keep = np.zeros(nc_b, np.uint8)
            keep[main_id] = 1
            merged_above = False
            for cid in order[1:]:
                area = sc_b[cid, cv2.CC_STAT_AREA]
                if area < 400:
                    continue
                c_y = float(ce_b[cid][1])
                if c_y < m_y - 0.35 * m_h:
                    keep[cid] = 1          # 在主体上方 -> 被手臂切开的肚皮，合并
                    merged_above = True
            bmask_main = (keep[lc_b] > 0).astype(np.uint8)
            if merged_above:
                # 用凸包把手臂造成的缺口补上
                p_main = np.column_stack(np.where(bmask_main > 0))
                if len(p_main) > 100:
                    p_xy = p_main[:, ::-1].reshape(-1, 1, 2).astype(np.int32)
                    hull = cv2.convexHull(p_xy)
                    hm = np.zeros_like(bmask)
                    cv2.fillConvexPoly(hm, hull, 1)
                    hm = hm * sil_bool.astype(np.uint8)
                    bmask_full = hm
                else:
                    bmask_full = bmask_main
            else:
                bmask_full = bmask_main
        pts = np.column_stack(np.where(bmask_full > 0))
        bmask = bmask_full
        bmask_bool = bmask > 0

        # 用完整肚皮重新算几何
        by2, bx2 = np.where(bmask_bool)
        if bx2.size:
            bw = bx2.max() - bx2.min() + 1
            bh = by2.max() - by2.min() + 1
            cx = int(bx2.mean() + bw * (cfg.badge_cx - 0.5))
            cy = int(by2.mean() + bh * (cfg.badge_cy - 0.5))

        # ---- 尺寸与位置 ----
        # 目标：让圆形徽章"正好填满"白肚皮。
        #
        # 肚皮通常是扁椭圆（宽 > 高），圆形不可能同时贴满四边，
        # 所以以"肚皮短边"为直径基准，此时圆会正好贴住上下沿。
        # 但肚皮可能被手臂压出缺口，直接按短边会溢出，
        # 因此再用"圆内落在肚皮上的比例"逐步收缩校正。
        #
        # 圆心：用白肚皮包围盒的中心。
        #
        # 试过三种取法，只有包围盒中心对准"可见的白肚皮"：
        #   · 距离变换峰值 -> 落在最厚处，01 偏右 21px
        #   · 像素质心     -> 03 偏左 7px
        #   · 拟合椭圆中心 -> 01 的肚皮被手压出缺口，椭圆中心偏向缺口一侧（偏左11、偏上14）
        # 包围盒中心 = 可见白肚皮的几何中心，与"看起来居中"一致。
        cx = int((bx2.min() + bx2.max()) / 2)
        cy = int((by2.min() + by2.max()) / 2)
        # 允许垂直/水平微调（相对肚皮尺寸）。badge_cy=0.5 表示正对肚皮中心。
        cx = int(cx + bw * (cfg.badge_cx - 0.5))
        cy = int(cy + bh * (cfg.badge_cy - 0.5))

        def belly_fit(radius: int) -> float:
            """以 (cx,cy) 为心、半径 radius 的圆内，落在肚皮上的比例。"""
            if radius <= 0:
                return 0.0
            yy, xx = np.mgrid[-radius:radius, -radius:radius]
            disk = (yy * yy + xx * xx) <= radius * radius
            py2 = np.clip(cy + yy[disk], 0, h - 1)
            px2 = np.clip(cx + xx[disk], 0, w - 1)
            return float(bmask[py2, px2].mean())

        # 基准直径 = 肚皮短边
        base = min(bw, bh)
        r_try = base / 2.0
        # 只有在"不做遮挡回填"时，才需要保守收缩，避免徽章溢出肚皮。
        # 开启遮挡回填后，溢出的部分会被身体/手臂盖回去，不必收缩，
        # 否则会被压小、四边露出白肚皮。
        if not cfg.arms_over_badge:
            for _ in range(40):
                if r_try <= 6 or belly_fit(int(r_try)) >= 0.88:
                    break
                r_try *= 0.94
        size = int(r_try * 2 * cfg.badge_scale)
        # 椭圆模式：宽高分别按肚皮尺寸定，使校徽贴合扁椭圆肚皮。
        if cfg.badge_ellipse:
            size_w = int(bw * cfg.badge_fill_x)
            size_h = int(bh * cfg.badge_fill_y)
        else:
            size_w = size
            size_h = size
    else:
        # ---- 没有白肚皮：贴在躯干正面中央 ----
        #
        # 09/11 号这类"大笑夹臂"姿态几乎没有白肚皮（实测中间区域饱和度 0.69，
        # 整片都是黄身体）。但示例里这种姿态的徽章同样是贴在胸腹正面的，
        # 所以不需要肚皮也能定位——用躯干的几何中心即可。
        #
        # 之前两个错误：
        #   1) 用包围盒垂直比例 -> 大笑图包围盒占满全高，徽章贴到嘴上
        #   2) 用最宽行区间         -> 尺寸系数过大，徽章压到下巴/被裁切
        # 现在：用剪影的"面积重心"定位。
        # 重心的物理意义是质量中心，头再大，重心也必然落在躯干上，
        # 不会像"行区间比例"那样随头部大小漂移。
        sil = masks["silhouette"] > 0.5
        row_w = sil.sum(axis=1).astype(np.float32)
        if row_w.max() > 0:
            # 每行宽度加权求垂直重心（比简单质心更贴近"躯干厚实处"）
            ys_all = np.arange(sil.shape[0], dtype=np.float32)
            cy = int((row_w * ys_all).sum() / max(row_w.sum(), 1e-3))
            # 尺寸用躯干中位宽度（躯干宽度序列的中位数，抗头部干扰）
            body_rows = row_w[row_w > row_w.max() * 0.35]
            trunk_w = float(np.median(body_rows)) if body_rows.size else row_w.max()
            size = int(trunk_w * cfg.badge_scale * 0.78)
        else:
            cy = int(by0 + (by1 - by0) * 0.60)
            size = int(body_w * cfg.badge_scale * 0.6)
        size_w = size
        size_h = size
        # 水平用质心（比包围盒中心稳）
        cx = int(xs.mean())

    # 安全约束：徽章圆心必须落在身体剪影内部，否则说明定位失败
    sil = masks["silhouette"] > 0.5
    cy = int(np.clip(cy, by0, by1))
    cx = int(np.clip(cx, bx0, bx1))
    if not sil[min(max(cy, 0), h - 1), min(max(cx, 0), w - 1)]:
        # 圆心不在身体内：向质心方向拉回来
        gt = xs.mean(), ys.mean()
        for _ in range(30):
            cx = int(cx + (gt[0] - cx) * 0.2)
            cy = int(cy + (gt[1] - cy) * 0.2)
            if sil[min(max(cy, 0), h - 1), min(max(cx, 0), w - 1)]:
                break

    size = max(16, size)
    size_w = max(16, size_w)
    size_h = max(16, size_h)

    # ---- 硬约束：徽章不能超出画面 ----
    # 只在未开启遮挡回填时按"身体覆盖率"收缩；开启回填后，
    # 超出身体的部分会被身体盖回去，无需收缩（收缩会导致徽章偏小、露白边）。
    sil_chk = masks["silhouette"] > 0.5
    h_img, w_img = sil_chk.shape[:2]
    if not cfg.arms_over_badge:
        for _ in range(40):
            r = size / 2.0
            yy0 = int(max(0, cy - r)); yy1 = int(min(h_img, cy + r))
            xx0 = int(max(0, cx - r)); xx1 = int(min(w_img, cx + r))
            if yy1 <= yy0 or xx1 <= xx0:
                break
            frag = sil_chk[yy0:yy1, xx0:xx1]
            # 圆内身体覆盖率：<0.85 说明溢出到身体外
            cover = float(frag.mean()) if frag.size else 0.0
            if cover > 0.85 or size <= 24:
                break
            size = int(size * 0.92)
    else:
        # 仅保证不被画布边缘裁切
        half = size / 2.0
        if cy - half < 0 or cy + half > h_img or cx - half < 0 or cx + half > w_img:
            size = int(min(size, 2 * min(cy, h_img - cy, cx, w_img - cx)) * 0.98)
        size = max(24, size)

    # ---- 硬约束：徽章不能压到嘴/五官 ----
    # 有些姿态（如大笑）嘴张得很低，几何中心算出来正好落在嘴上。
    # 这里检查徽章圆内是否覆盖了五官遮罩，若覆盖就整体下移，直到避开。
    feat = masks.get("feature")
    if feat is not None:
        h_img, w_img = feat.shape[:2]
        r = size / 2.0
        for _ in range(24):
            yy0 = int(max(0, cy - r)); yy1 = int(min(h_img, cy + r))
            xx0 = int(max(0, cx - r)); xx1 = int(min(w_img, cx + r))
            if xx1 <= xx0 or yy1 <= yy0:
                break
            frag = feat[yy0:yy1, xx0:xx1]
            if frag.size == 0 or float(frag.mean()) < 0.02:
                break                      # 已避开五官
            cy += max(1, int(r * 0.25))     # 往下移
            if cy > by1:                    # 移出身体则放弃
                break
        cy = int(np.clip(cy, by0 + r * 0.2, by1 - r * 0.2))

    if os.environ.get("DSH_DEBUG_BADGE"):
        print(f"[badge] belly bbox {bw}x{bh} -> center=({cx},{cy}) "
              f"size={size_w}x{size_h} ellipse={cfg.badge_ellipse}")
    # ---- 遮挡：徽章只显示在白肚皮范围内 ----
    # 肚皮之外的部分（手臂、身体）要盖回徽章上方。
    # 这样同时解决两种情况：
    #   · 02 抱胸：完整肚皮内的手臂缺口 -> 手臂压住徽章中段
    #   · 01 捧腹：徽章右侧越出肚皮 -> 被手臂盖住，不再"画在手臂上"
    # 判据：身体剪影内、但不在白肚皮上的像素 = 遮挡物。
    if cfg.arms_over_badge and belly_found:
        belly_raw = (masks["belly"] > 0.5).astype(np.uint8)
        k_occ = max(3, int(size * 0.02) | 1)
        belly_dil = cv2.dilate(belly_raw, np.ones((k_occ, k_occ), np.uint8))
        yy_o, xx_o = np.mgrid[0:h, 0:w]
        # 遮挡范围取徽章外接椭圆稍大一圈，保证盖得住
        ax = size_w * 0.62
        ay = size_h * 0.62
        ell = (((xx_o - cx) / max(ax, 1)) ** 2 + ((yy_o - cy) / max(ay, 1)) ** 2) <= 1.0
        occ = ((belly_dil == 0) & sil & ell).astype(np.float32)
        if occ.sum() > 0:
            occ_mask = cv2.GaussianBlur(occ, (0, 0), max(1.0, size * 0.012))
            # 归一化回 0~1，避免模糊后峰值不足导致盖不干净
            mx = float(occ_mask.max())
            if mx > 1e-3:
                occ_mask = np.clip(occ_mask / mx, 0, 1)

    # ---- 超采样：4 倍画布上合成 ----
    ss = cfg.badge_supersample
    big = cv2.resize(canvas.astype(np.float32) / 255.0, (w * ss, h * ss),
                     interpolation=cv2.INTER_CUBIC)
    big = np.clip(big, 0, 1)
    _blend_badge_on(big, badge, masks, cfg, body_w, cx * ss, cy * ss,
                    size_w * ss, size_h * ss)

    # ---- 手臂盖回徽章上方：形成"徽章铺满肚皮、手臂压住一部分"的层次 ----
    # 02 号这种抱胸姿势，手臂是黄色的（不是灰色手掌），手部遮罩抓不到，
    # 但它在"完整肚皮"内部形成了缺口。这些缺口就是压在肚皮上的手臂，
    # 必须把身体（换色后、未贴徽章的版本）重新盖回徽章之上。
    if occ_mask is not None:
        occ_big = cv2.resize(occ_mask, (w * ss, h * ss), interpolation=cv2.INTER_LINEAR)
        occ_big = np.clip(occ_big, 0, 1)[..., None]
        base = cv2.resize(canvas.astype(np.float32) / 255.0, (w * ss, h * ss),
                          interpolation=cv2.INTER_CUBIC)
        big = big * (1 - occ_big) + np.clip(base, 0, 1) * occ_big

    # ---- 手部重新叠回最上层：形成"抱着校徽"的层次 ----
    if cfg.hands_over_badge and original is not None:
        src = cv2.resize(original.astype(np.float32) / 255.0, (w * ss, h * ss),
                         interpolation=cv2.INTER_CUBIC)
        hand_m = cv2.resize(masks["hand"], (w * ss, h * ss),
                            interpolation=cv2.INTER_LINEAR)
        if cfg.hands_feather > 0:
            hand_m = cv2.GaussianBlur(hand_m, (0, 0), cfg.hands_feather * ss)
        hand_m = np.clip(hand_m, 0, 1)[..., None]
        big = big * (1 - hand_m) + np.clip(src, 0, 1) * hand_m

    small = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    return (np.clip(small, 0, 1) * 255).astype(np.uint8)


# ---------------------------------------------------------------- 入口

_OVERRIDES_PATH = Path(__file__).with_name("overrides.json")
_overrides_cache: dict | None = None


def load_overrides() -> dict:
    """读取按图微调参数（overrides.json）。不同的奶蛙姿态需要不同的徽章尺寸。"""
    global _overrides_cache
    if _overrides_cache is None:
        try:
            import json
            _overrides_cache = json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _overrides_cache = {}
    return _overrides_cache


def cfg_for(path: str | Path, base: RenderConfig | None = None) -> RenderConfig:
    """取某张图应使用的配置：默认值 + 该图的覆盖项。"""
    from dataclasses import replace

    cfg = base or RenderConfig()
    ov = load_overrides().get(Path(path).name)
    if isinstance(ov, dict):
        clean = {k: v for k, v in ov.items() if not k.startswith("_")}
        cfg = replace(cfg, **clean)
    return cfg


def render(frog_path: str | Path, brand: Brand, badge_path: str | Path,
           cfg: RenderConfig | None = None):
    """完整流程：分区 -> 换色 -> 贴徽章。

    返回 (最终结果, 仅换色的中间结果, 遮罩)。
    cfg 为 None 时自动套用该图的 overrides。
    """
    cfg = cfg or cfg_for(frog_path)
    rgb = _load_rgba(frog_path)
    masks = build_masks(rgb)
    stage1 = recolor(rgb, masks, brand, cfg)
    badge = make_badge(badge_path, brand)
    stage2 = apply_badge(stage1, badge, masks, cfg, original=rgb)
    return stage2, stage1, masks
