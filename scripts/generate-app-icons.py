#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSET_SOURCE = ROOT / "assets" / "TeXada-icon-source.png"
TAURI_ICONS = ROOT / "tauri-shell" / "src-tauri" / "icons"

SIZE = 1024
SCALE = 3
WORK_SIZE = SIZE * SCALE

BG_BASE = (26, 27, 38)
BG_SURFACE = (36, 40, 59)
BG_ELEVATED = (47, 51, 73)
ACCENT_BLUE = (122, 162, 247)
ACCENT_CYAN = (125, 207, 255)
ACCENT_GREEN = (158, 206, 106)
ACCENT_PURPLE = (187, 154, 247)
ACCENT_ORANGE = (255, 158, 100)

FONT_MATH = Path("/System/Library/Fonts/Supplemental/STIXTwoMath.otf")
FONT_TEXT = Path("/System/Library/Fonts/Supplemental/STIXGeneralBol.otf")


def scaled(value: int) -> int:
    return value * SCALE


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_panel_gradient() -> Image.Image:
    image = Image.new("RGBA", (WORK_SIZE, WORK_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(WORK_SIZE):
        t = y / max(1, WORK_SIZE - 1)
        if t < 0.45:
            color = mix(BG_ELEVATED, BG_SURFACE, t / 0.45)
        else:
            color = mix(BG_SURFACE, BG_BASE, (t - 0.45) / 0.55)
        draw.line([(0, y), (WORK_SIZE, y)], fill=(*color, 255))
    return image


def apply_blush(panel: Image.Image, mask: Image.Image) -> Image.Image:
    blush = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(blush)
    draw.ellipse(
        [scaled(110), scaled(70), scaled(750), scaled(650)],
        fill=(*ACCENT_BLUE, 34),
    )
    draw.ellipse(
        [scaled(380), scaled(320), scaled(1060), scaled(1090)],
        fill=(*ACCENT_PURPLE, 32),
    )
    draw.ellipse(
        [scaled(120), scaled(560), scaled(520), scaled(1030)],
        fill=(*ACCENT_CYAN, 20),
    )
    blush = blush.filter(ImageFilter.GaussianBlur(scaled(68)))
    blush.putalpha(Image.composite(blush.getchannel("A"), Image.new("L", panel.size, 0), mask))
    return Image.alpha_composite(panel, blush)


def draw_panel(canvas: Image.Image) -> None:
    rect = [scaled(96), scaled(96), scaled(928), scaled(928)]
    radius = scaled(184)
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(rect, radius=radius, fill=255)

    panel = make_panel_gradient()
    panel = apply_blush(panel, mask)
    panel.putalpha(mask)
    canvas.alpha_composite(panel)


def text_position(
    text: str,
    font: ImageFont.FreeTypeFont,
    center: tuple[int, int],
) -> tuple[int, int]:
    scratch = Image.new("L", (1, 1))
    draw = ImageDraw.Draw(scratch)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = scaled(center[0]) - width // 2 - bbox[0]
    y = scaled(center[1]) - height // 2 - bbox[1]
    return x, y


def make_text_mask(
    text: str,
    font: ImageFont.FreeTypeFont,
    center: tuple[int, int],
) -> Image.Image:
    mask = Image.new("L", (WORK_SIZE, WORK_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    draw.text(text_position(text, font, center), text, font=font, fill=255)
    return mask


def gradient_from_top_to_bottom(
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
) -> Image.Image:
    image = Image.new("RGBA", (WORK_SIZE, WORK_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(WORK_SIZE):
        color = mix(top, bottom, y / max(1, WORK_SIZE - 1))
        draw.line([(0, y), (WORK_SIZE, y)], fill=(*color, 255))
    return image


def draw_gradient_text(
    canvas: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    center: tuple[int, int],
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
    shadow_alpha: int = 92,
) -> None:
    mask = make_text_mask(text, font, center)

    shadow_mask = Image.new("L", (WORK_SIZE, WORK_SIZE), 0)
    shadow_mask.paste(mask, (scaled(16), scaled(22)))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(scaled(10)))
    shadow = Image.new("RGBA", (WORK_SIZE, WORK_SIZE), (0, 0, 0, 0))
    shadow.putalpha(shadow_mask.point(lambda value: min(value, shadow_alpha)))
    canvas.alpha_composite(shadow)

    fill = gradient_from_top_to_bottom(top, bottom)
    fill.putalpha(mask)
    canvas.alpha_composite(fill)

    highlight_mask = mask.filter(ImageFilter.GaussianBlur(scaled(1)))
    highlight = Image.new("RGBA", (WORK_SIZE, WORK_SIZE), (255, 255, 255, 0))
    highlight.putalpha(highlight_mask.point(lambda value: round(value * 0.12)))
    canvas.alpha_composite(highlight)


def draw_spark(canvas: Image.Image) -> None:
    layer = Image.new("RGBA", (WORK_SIZE, WORK_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = scaled(748)
    cy = scaled(327)
    r1 = scaled(54)
    r2 = scaled(15)
    points = [
        (cx, cy - r1),
        (cx + r2, cy - r2),
        (cx + r1, cy),
        (cx + r2, cy + r2),
        (cx, cy + r1),
        (cx - r2, cy + r2),
        (cx - r1, cy),
        (cx - r2, cy - r2),
    ]
    draw.polygon(points, fill=(*ACCENT_ORANGE, 245))
    glow = layer.filter(ImageFilter.GaussianBlur(scaled(14)))
    glow.putalpha(glow.getchannel("A").point(lambda value: round(value * 0.55)))
    canvas.alpha_composite(glow)
    canvas.alpha_composite(layer)


def render_source_icon() -> Image.Image:
    if not FONT_MATH.exists():
        raise FileNotFoundError(FONT_MATH)
    if not FONT_TEXT.exists():
        raise FileNotFoundError(FONT_TEXT)

    canvas = Image.new("RGBA", (WORK_SIZE, WORK_SIZE), (0, 0, 0, 0))
    draw_panel(canvas)

    brace_font = ImageFont.truetype(str(FONT_TEXT), scaled(390))
    integral_font = ImageFont.truetype(str(FONT_MATH), scaled(595))
    sigma_font = ImageFont.truetype(str(FONT_MATH), scaled(455))

    draw_gradient_text(canvas, "{", brace_font, (230, 531), ACCENT_GREEN, (71, 172, 115), 84)
    draw_gradient_text(canvas, "}", brace_font, (800, 531), (210, 150, 255), (126, 87, 222), 84)
    draw_gradient_text(canvas, "∫", integral_font, (385, 520), (182, 211, 255), (66, 160, 238), 110)
    draw_gradient_text(canvas, "Σ", sigma_font, (596, 532), (206, 189, 255), (127, 91, 231), 100)
    draw_spark(canvas)

    return canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def save_tauri_pngs(source: Image.Image) -> None:
    TAURI_ICONS.mkdir(parents=True, exist_ok=True)
    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
    }
    for name, size in sizes.items():
        icon = source.resize((size, size), Image.Resampling.LANCZOS)
        clear_outer_edge(icon).save(TAURI_ICONS / name)


def save_ico(source: Image.Image) -> None:
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    source.save(TAURI_ICONS / "icon.ico", sizes=sizes)


def clear_outer_edge(icon: Image.Image) -> Image.Image:
    icon = icon.copy()
    pixels = icon.load()
    width, height = icon.size
    for x in range(width):
        pixels[x, 0] = (*pixels[x, 0][:3], 0)
        pixels[x, height - 1] = (*pixels[x, height - 1][:3], 0)
    for y in range(height):
        pixels[0, y] = (*pixels[0, y][:3], 0)
        pixels[width - 1, y] = (*pixels[width - 1, y][:3], 0)
    return icon


def save_icns(source: Image.Image) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        iconset = Path(tmpdir) / "TeXada.iconset"
        iconset.mkdir()
        sizes = {
            "icon_16x16.png": 16,
            "icon_16x16@2x.png": 32,
            "icon_32x32.png": 32,
            "icon_32x32@2x.png": 64,
            "icon_128x128.png": 128,
            "icon_128x128@2x.png": 256,
            "icon_256x256.png": 256,
            "icon_256x256@2x.png": 512,
            "icon_512x512.png": 512,
            "icon_512x512@2x.png": 1024,
        }
        for name, size in sizes.items():
            source.resize((size, size), Image.Resampling.LANCZOS).save(iconset / name)
        output = Path(tmpdir) / "TeXada.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(output)], check=True)
        shutil.copyfile(output, TAURI_ICONS / "icon.icns")


def main() -> None:
    source = render_source_icon()
    ASSET_SOURCE.parent.mkdir(parents=True, exist_ok=True)
    source.save(ASSET_SOURCE)
    save_tauri_pngs(source)
    save_ico(source)
    save_icns(source)


if __name__ == "__main__":
    main()
