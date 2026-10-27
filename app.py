"""奶蛙 × 校徽生成器 —— 本地网页服务（零第三方依赖，仅用 Python 标准库）。

启动：
    python app.py
浏览器打开 http://127.0.0.1:8000

功能：
    · 用户上传自己的奶蛙原图（任意姿态）
    · 用户上传自己的校徽图片
    · 程序自动提取校徽主色、把奶蛙换成校徽配色，并把校徽以椭圆贴在白肚皮上
    · 结果可下载为 PNG
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))

import cv2                                            # noqa: E402
import numpy as np                                    # noqa: E402
from PIL import Image                                 # noqa: E402

from brand import _load_rgba, make_badge, parse_brand  # noqa: E402
from recolor import RenderConfig, cfg_for, render      # noqa: E402

PACK = ROOT / "奶蛙表情包"
WEB = ROOT / "web"
TMP = ROOT / "output" / "_tmp"
PORT = 8000

# 内置示例素材（可选快捷入口，用户也可以完全用自己的图）
PRESETS = [
    {"id": "01", "file": "01_3_001_pengfu-daxiao.png", "label": "捧腹大笑"},
    {"id": "02", "file": "02_3_005_chensi.png",        "label": "抱胸沉思"},
    {"id": "03", "file": "03_3_008_zhenjing.png",      "label": "震惊"},
    {"id": "06", "file": "06_3_007_daxiao-zhiqian.png", "label": "大笑之前"},
    {"id": "07", "file": "07_3_010_baotou-daxiao.png", "label": "抱头大笑"},
    {"id": "09", "file": "09_3_019_miyan-daxiao.png",  "label": "眯眼大笑"},
    {"id": "11", "file": "11_3_021_yangtian-daxiao.png", "label": "仰天大笑"},
]
PRESET_BY_ID = {m["id"]: m for m in PRESETS}

_thumb_cache: dict[str, bytes] = {}
_brand_cache: dict[str, dict] = {}
_lock = threading.Lock()


def _decode_data_url(data_url: str) -> bytes:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    if not data_url:
        raise ValueError("没有收到图片数据")
    return base64.b64decode(data_url)


def _save_png(raw: bytes, stem: str) -> Path:
    """把任意格式图片统一转存为 PNG，返回路径。"""
    TMP.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    p = TMP / f"{stem}_{uuid.uuid4().hex[:8]}.png"
    img.save(p, format="PNG")
    return p


def thumb_bytes(meme: dict, size: int = 260) -> bytes:
    key = f"{meme['id']}_{size}"
    if key in _thumb_cache:
        return _thumb_cache[key]
    rgb = _load_rgba(PACK / meme["file"])
    im = Image.fromarray(rgb).convert("RGBA")
    im.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    data = buf.getvalue()
    _thumb_cache[key] = data
    return data


def load_brand(logo_path: Path) -> dict:
    raw = logo_path.read_bytes()
    key = hashlib.sha256(raw).hexdigest()
    with _lock:
        if key in _brand_cache:
            return _brand_cache[key]
    brand = parse_brand(logo_path)
    badge = make_badge(logo_path, brand)
    info = {"brand": brand, "badge": badge, "hex": brand.primary}
    with _lock:
        _brand_cache[key] = info
    return info


def render_free(base_path: Path, logo_path: Path) -> tuple[bytes, str]:
    """用任意原图 + 任意校徽生成成品。"""
    info = load_brand(logo_path)
    cfg = cfg_for(base_path, RenderConfig(l_shift_strength=0.95))
    result, _, masks = render(base_path, info["brand"], logo_path, cfg)
    im = Image.fromarray(result)
    buf = io.BytesIO()
    im.save(buf, format="PNG")

    # 若这张图没检测到白肚皮，附带提示（仍返回图片，供用户自行判断）
    belly_ratio = float((masks["belly"] > 0.5).mean())
    warn = "" if belly_ratio > 0.004 else "no-belly"
    return buf.getvalue(), info["hex"] + ("" if not warn else "|" + warn)


class Handler(BaseHTTPRequestHandler):
    server_version = "NaiwaBadge/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                    # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "index.html").read_bytes(),
                              "text/html; charset=utf-8")
        if path == "/api/presets":
            body = json.dumps(PRESETS, ensure_ascii=False).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        if path.startswith("/thumb/"):
            mid = path[len("/thumb/"):].replace(".png", "")
            meme = PRESET_BY_ID.get(mid)
            if not meme:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, thumb_bytes(meme), "image/png")
        if path == "/preset/":
            pass
        if path.startswith("/preset/"):
            mid = path[len("/preset/"):].replace(".png", "")
            meme = PRESET_BY_ID.get(mid)
            if not meme:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, (PACK / meme["file"]).read_bytes(), "image/png")
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):                                   # noqa: N802
        if self.path.split("?")[0] != "/api/render":
            return self._send(404, b"not found", "text/plain")
        base_file = logo_file = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")

            # 原图：只能从内置素材库选择（按需求限制，不接受用户上传原图）
            preset_id = str(payload.get("preset") or "")
            if not preset_id:
                raise ValueError("请先选择一张奶蛙表情")
            meme = PRESET_BY_ID.get(preset_id)
            if not meme:
                raise ValueError(f"未知表情: {preset_id}")
            base_file = PACK / meme["file"]

            logo_url = payload.get("logo") or ""
            if not logo_url:
                raise ValueError("请先上传校徽图片")
            logo_file = _save_png(_decode_data_url(logo_url), "logo")

            png, meta = render_free(base_file, logo_file)
            hexc, _, warn = meta.partition("|")
            return self._send(200, png, "image/png",
                              {"X-Brand-Color": hexc,
                               "X-Warn": warn,
                               "Content-Disposition": 'inline; filename="naiwa_out.png"'})
        except Exception as exc:                        # noqa: BLE001
            import traceback
            traceback.print_exc()          # 服务端留痕，便于排查
            msg = json.dumps(
                {"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False
            ).encode("utf-8")
            return self._send(400, msg, "application/json; charset=utf-8")
        finally:
            for p in (base_file, logo_file):
                if p is not None and str(p).startswith(str(TMP)):
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass


def main():
    if not PACK.exists():
        print("找不到素材目录:", PACK)
        sys.exit(1)
    TMP.mkdir(parents=True, exist_ok=True)

    # 端口可能被上一次残留的服务占用，自动往后找一个可用端口
    srv = None
    port = PORT
    for candidate in range(PORT, PORT + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if srv is None:
        print(f"端口 {PORT}~{PORT + 19} 都被占用，无法启动")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    print(f"服务已启动: {url}")
    print("在浏览器打开上面的地址即可使用（本窗口关闭后服务停止）")

    # 自动打开浏览器，省去手动输入地址（避免误用 file:// 打开网页）
    if "--no-browser" not in sys.argv:
        import threading
        import webbrowser

        def _open():
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

        threading.Timer(1.0, _open).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
