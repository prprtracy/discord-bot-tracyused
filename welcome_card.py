"""
欢迎图片生成模块。
布局：完整背景图 + 中央半透明圆角黑色展示区 + 圆形头像 + 三行居中文字
依赖：Pillow >= 8.2（pip install Pillow）、aiohttp（已有）
"""
import io
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

# ── 画布尺寸 ───────────────────────────────────────────────────
CARD_W, CARD_H = 960, 540

# ── 中央展示区（圆角矩形）─────────────────────────────────────
PANEL_W      = int(CARD_W * 0.72)   # 690 px
PANEL_H      = int(CARD_H * 0.62)   # 335 px
PANEL_RADIUS = 28                    # 圆角半径
PANEL_ALPHA  = 165                   # 黑色透明度（0-255，165 ≈ 65%）

# ── 头像 ───────────────────────────────────────────────────────
AVATAR_SIZE   = 130   # 直径
AVATAR_BORDER = 6     # 白色描边宽度

# ── 背景图 URL ────────────────────────────────────────────────
BACKGROUND_URL = (
    "https://i.pinimg.com/originals/90/52/8a/"
    "90528a48da241f45eac96fdca39d88e7.jpg"
)

# ── 字体 ──────────────────────────────────────────────────────
_BOLD    = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
_REGULAR = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for p in (_BOLD if bold else _REGULAR):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ── 网络图片下载 ───────────────────────────────────────────────
async def _fetch(url: str, timeout: int = 10) -> Image.Image | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout),
                             headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status != 200:
                    print(f"[欢迎图] HTTP {r.status} → {url[:60]}")
                    return None
                return Image.open(io.BytesIO(await r.read())).convert("RGBA")
    except Exception as e:
        print(f"[欢迎图] 下载失败 {url[:60]}：{e}")
        return None


# ── 圆形头像（含白色描边）────────────────────────────────────
def _circle_avatar(img: Image.Image) -> Image.Image:
    total = AVATAR_SIZE + AVATAR_BORDER * 2
    out   = Image.new("RGBA", (total, total), (0, 0, 0, 0))

    # 白色外圈
    ImageDraw.Draw(out).ellipse((0, 0, total - 1, total - 1),
                                fill=(255, 255, 255, 255))
    # 圆形头像蒙版
    av   = img.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (AVATAR_SIZE, AVATAR_SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR_SIZE - 1, AVATAR_SIZE - 1), fill=255)
    out.paste(av, (AVATAR_BORDER, AVATAR_BORDER), mask)
    return out


# ── 居中绘文字，返回下一行 y ──────────────────────────────────
def _text_center(draw: ImageDraw.ImageDraw, text: str,
                 font: ImageFont.FreeTypeFont,
                 cx: int, y: int, fill) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((cx - w // 2, y), text, font=font, fill=fill)
    return y + h


# ── 主函数 ─────────────────────────────────────────────────────
async def generate_welcome_card(
    dcid: str,
    member_count: int,
    avatar_url: str | None,
) -> io.BytesIO:
    """
    生成欢迎图，返回 PNG BytesIO。
    任何步骤失败均有兜底，保证函数一定返回图片。
    """

    # ── 1. 背景（整张清晰，不整体压暗）──────────────────────
    bg_src = await _fetch(BACKGROUND_URL)
    if bg_src is None:
        bg = Image.new("RGBA", (CARD_W, CARD_H), (35, 38, 47, 255))
    else:
        bg = bg_src.resize((CARD_W, CARD_H), Image.LANCZOS).convert("RGBA")

    # ── 2. 中央半透明圆角矩形展示区 ──────────────────────────
    panel_x = (CARD_W - PANEL_W) // 2   # 135
    panel_y = (CARD_H - PANEL_H) // 2   # 102

    # 单独图层绘制圆角矩形，再 alpha-composite 到背景
    panel_layer = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    panel_draw  = ImageDraw.Draw(panel_layer)
    panel_draw.rounded_rectangle(
        (panel_x, panel_y, panel_x + PANEL_W, panel_y + PANEL_H),
        radius=PANEL_RADIUS,
        fill=(0, 0, 0, PANEL_ALPHA),
    )
    bg = Image.alpha_composite(bg, panel_layer)

    draw = ImageDraw.Draw(bg)
    cx   = CARD_W // 2   # 水平中心

    # ── 3. 圆形头像 ────────────────────────────────────────────
    av_src = await _fetch(avatar_url) if avatar_url else None
    if av_src is None:
        av_src = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (100, 104, 115, 255))

    av_layer = _circle_avatar(av_src)
    aw = av_layer.width   # AVATAR_SIZE + AVATAR_BORDER*2  = 142

    # 头像顶部：展示区顶部 + 28px padding
    av_x = cx - aw // 2
    av_y = panel_y + 28
    bg.paste(av_layer, (av_x, av_y), av_layer)

    # ── 4. 文字区（头像底部 + 18px 间距起）────────────────────
    f_name  = _font(38, bold=True)
    f_sub   = _font(22, bold=False)
    f_count = _font(18, bold=False)

    ty = av_y + aw + 18

    # 行 1：用户名
    ty = _text_center(draw, dcid, f_name, cx, ty,
                      fill=(255, 255, 255, 245))
    ty += 12

    # 行 2：just joined the server
    ty = _text_center(draw, "just joined the server", f_sub, cx, ty,
                      fill=(195, 200, 210, 220))
    ty += 14

    # 行 3：Member #N
    _text_center(draw, f"Member #{member_count}", f_count, cx, ty,
                 fill=(147, 197, 253, 200))

    # ── 5. 输出 ────────────────────────────────────────────────
    out = io.BytesIO()
    bg.convert("RGB").save(out, format="PNG", optimize=True)
    out.seek(0)
    return out
