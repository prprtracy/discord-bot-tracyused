"""Render the public VALORANT matchup from the confirmed roster."""
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


@dataclass(frozen=True)
class CardPlayer:
    name: str
    passive: str
    avatar: bytes | None


@lru_cache(maxsize=24)
def font(size, bold=False):
    weight = "Bold" if bold else "Regular"
    for path in (f"/usr/share/fonts/opentype/noto/NotoSansCJK-{weight}.ttc",
                 f"C:/Windows/Fonts/msjh{'bd' if bold else ''}.ttc",
                 "/System/Library/Fonts/PingFang.ttc",
                 "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise OSError("Install a Chinese font (Debian/Ubuntu: fonts-noto-cjk)")


def lines_for(text, face, width, limit):
    lines = [""]
    for ch in " ".join(text.split()):
        if face.getlength(lines[-1] + ch) > width:
            if len(lines) == limit:
                while lines[-1] and face.getlength(lines[-1] + "…") > width:
                    lines[-1] = lines[-1][:-1]
                lines[-1] += "…"
                break
            lines.append("")
        lines[-1] += ch
    return lines


def render_matchup(background, name, localized, number, teams):
    with Image.open(background) as source:
        canvas = ImageOps.fit(source.convert("RGB"), (1600, 900), method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((0, 0, 1600, 900), fill=(7, 16, 27, 134))
    white = "#fff7e9"
    def label(x, y, value, size, color=white, anchor="mm", bold=False):
        draw.text((x, y), value, font=font(size, bold), fill=color, anchor=anchor)

    label(800, 51, f"第 {number} 次趣味瓦内战", 23)
    label(800, 117, localized, 69, bold=True)
    label(800, 181, name.upper(), 27, bold=True)
    with Image.open(Path(__file__).resolve().parent / "assets" / "spike.png") as spike:
        canvas.paste(spike, (800 - spike.width // 2, 209), spike)
    draw.polygon([(800, 427), (867, 494), (800, 561), (733, 494)],
                 fill=(9, 20, 30, 145), outline=(255, 255, 255, 145), width=2)
    label(800, 494, "VS", 48, bold=True)

    for team, x, accent in (("A", 45, "#61e0cb"), ("B", 995, "#ff566b")):
        right = team == "B"
        anchor = "rm" if right else "lm"
        label(x + (560 if right else 0), 168, f"{team} 队", 35, accent, anchor, True)
        draw.line((x, 203, x+560, 203), fill=accent, width=3)
        players = teams[team]
        for i, player in enumerate(players):
            y = 225 + (5-len(players))*62 + i*124
            draw.rectangle((x, y, x+560, y+110), fill=(9, 19, 30, 228))
            edge = x+555 if right else x
            draw.rectangle((edge,y,edge+5,y+110), fill=accent)
            ax = x+456 if right else x+16
            draw.ellipse((ax,y+11,ax+88,y+99), fill=accent)
            avatar = None
            if player.avatar:
                try:
                    with Image.open(BytesIO(player.avatar)) as src:
                        avatar = ImageOps.fit(src.convert("RGB"), (84, 84))
                except OSError:
                    pass
            if avatar:
                mask = Image.new("L", avatar.size)
                ImageDraw.Draw(mask).ellipse((0, 0, 83, 83), fill=255)
                canvas.paste(avatar, (ax+2,y+13), mask)
            else:
                label(ax+44, y+55, player.name[:1], 36, "#12202d", bold=True)
            tx = x+440 if right else x+120
            label(tx,y+28,lines_for(player.name,font(31,True),420,1)[0],31,anchor=anchor,bold=True)
            for j, line in enumerate(lines_for(player.passive,font(22),420,2)):
                label(tx,y+66+j*27,line,22,"#d3e0e7",anchor)
    output = BytesIO()
    canvas.save(output, "JPEG", quality=91, optimize=True)
    return output.getvalue()
