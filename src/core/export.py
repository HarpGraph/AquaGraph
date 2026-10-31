"""Сохранение слоёв (PNG RGBA) и контрольных картинок."""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .compose import composite

OUTLINE_COLOR = (40, 40, 40)
MM_PER_INCH = 25.4


def mm_to_px(mm, dpi):
    return max(1, round(mm / MM_PER_INCH * dpi))


def registration_marks(size_px, dpi, inset_mm=8.0, arm_mm=5.0, thickness_mm=0.4):
    """Метки совмещения ⊕ в четырёх углах листа. Возвращает маску (H, W) float32 [0..1]."""
    w, h = size_px
    thick = max(1, mm_to_px(thickness_mm, dpi))
    arm = max(3, mm_to_px(arm_mm, dpi))
    inset = max(mm_to_px(inset_mm, dpi), arm + thick)
    radius = max(2, round(arm * 0.6))
    mask = np.zeros((h, w), dtype=np.uint8)
    for cx in (inset, w - 1 - inset):
        for cy in (inset, h - 1 - inset):
            if 0 <= cx < w and 0 <= cy < h:
                cv2.line(mask, (cx - arm, cy), (cx + arm, cy), 255, thick, cv2.LINE_AA)
                cv2.line(mask, (cx, cy - arm), (cx, cy + arm), 255, thick, cv2.LINE_AA)
                cv2.circle(mask, (cx, cy), radius, 255, thick, cv2.LINE_AA)
    return mask.astype(np.float32) / 255.0


def export_layer_set(layers, out_dir, size_px, dpi, white_background=False, marks=None, mark_color=OUTLINE_COLOR):
    """Экспорт набора слоёв в PNG одного размера.

    layers: список (имя_файла_без_расширения, (r, g, b), alpha (H, W) float [0..1]).
    size_px: (ширина, высота). В PNG записывается DPI, чтобы приложение могло выставить масштаб 1:1.
    white_background=True — слой кладётся на белый, без прозрачности.
    marks: маска меток совмещения размера size_px; рисуется на каждом слое цветом mark_color."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = size_px
    paths = []
    for stem, rgb, alpha in layers:
        interp = cv2.INTER_AREA if w < alpha.shape[1] else cv2.INTER_LINEAR
        a = np.clip(cv2.resize(alpha.astype(np.float32), (w, h), interpolation=interp), 0.0, 1.0)
        rgba = np.empty((h, w, 4), dtype=np.uint8)
        rgba[..., :3] = rgb
        rgba[..., 3] = np.rint(a * 255).astype(np.uint8)
        if marks is not None:
            on = marks > 0
            rgba[on, :3] = mark_color
            rgba[..., 3] = np.maximum(rgba[..., 3], np.rint(marks * 255).astype(np.uint8))
        img = Image.fromarray(rgba, "RGBA")
        if white_background:
            img = Image.alpha_composite(Image.new("RGBA", img.size, (255, 255, 255, 255)), img).convert("RGB")
        path = out_dir / f"{stem}.png"
        img.save(path, dpi=(dpi, dpi))
        paths.append(path)
    return paths


def save_layers(t, paints, out_dir, opaque_background=False):
    """По одному PNG на краску: цвет = краска, alpha = густота.
    opaque_background=True — вместо прозрачности слой кладётся на белый (для просмотрщиков без alpha)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, (layer, paint) in enumerate(zip(t, paints), start=1):
        h, w = layer.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[..., :3] = paint.rgb
        rgba[..., 3] = np.rint(layer * 255).astype(np.uint8)
        img = Image.fromarray(rgba, "RGBA")
        if opaque_background:
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(bg, img).convert("RGB")
        path = out_dir / f"{i:02d}_{paint.id}.png"
        img.save(path)
        paths.append(path)
    return paths


def save_comparison(original_rgb, result_rgb, path):
    Image.fromarray(np.hstack([original_rgb, result_rgb])).save(path)


def save_contact_sheet(original_rgb, result_rgb, t, paints, path, cols=4, title=""):
    """Оригинал, результат и каждый слой отдельно (на белой бумаге) с подписями."""
    from .palettes import paints_od

    h, w = original_rgb.shape[:2]
    scale = 0.5
    tw, th = int(w * scale), int(h * scale)
    od = paints_od(paints)
    tiles = [(Image.fromarray(original_rgb), "original"), (Image.fromarray(result_rgb), "result")]
    for layer, paint, o in zip(t, paints, od):
        tiles.append((Image.fromarray(composite(layer[None], o[None])), f"{paint.name_en}  max {layer.max():.2f}"))

    rows = -(-len(tiles) // cols)
    label_h = 18
    sheet = Image.new("RGB", (cols * tw, rows * (th + label_h)), (60, 60, 60))
    draw = ImageDraw.Draw(sheet)
    for n, (img, label) in enumerate(tiles):
        x, y = (n % cols) * tw, (n // cols) * (th + label_h)
        sheet.paste(img.resize((tw, th), Image.LANCZOS), (x, y + label_h))
        draw.text((x + 4, y + 3), label, fill=(255, 255, 255))
    if title:
        draw.text((tw * 2 + 4, 3), title, fill=(255, 220, 120))
    sheet.save(path)
