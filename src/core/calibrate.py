"""Калибровка краски по фото пробника: мазки разной густоты + чистая бумага."""
import numpy as np

from .color import OD_FLOOR, od_to_rgb, srgb_to_linear


def sample_patch(image_rgb, x, y, radius):
    """Медианный цвет квадратного пятна вокруг точки (x, y) на изображении (H, W, 3 uint8)."""
    h, w = image_rgb.shape[:2]
    x0, x1 = max(int(x) - radius, 0), min(int(x) + radius + 1, w)
    y0, y1 = max(int(y) - radius, 0), min(int(y) + radius + 1, h)
    patch = image_rgb[y0:y1, x0:x1].reshape(-1, 3)
    if len(patch) == 0:
        raise ValueError("Точка вне изображения")
    return tuple(int(v) for v in np.median(patch, axis=0))


def estimate_paint_rgb(samples, densities, paper=None):
    """RGB краски на полной густоте.

    samples: цвета мазков (n, 3 uint8); densities: их густота относительно полной (0..1];
    paper: цвет чистой бумаги на том же фото — по нему выравнивается баланс белого и яркость.
    Модель та же, что в расчёте слоёв: оптическая плотность пропорциональна густоте."""
    samples = np.asarray(samples, dtype=np.float32) / 255.0
    t = np.asarray(densities, dtype=np.float32)
    if len(samples) == 0 or len(samples) != len(t) or np.any(t <= 0):
        raise ValueError("Нужен хотя бы один мазок с положительной густотой")
    lin = srgb_to_linear(samples)
    if paper is not None:
        lin = lin / np.maximum(srgb_to_linear(np.asarray(paper, dtype=np.float32) / 255.0), 1e-3)
    od = -np.log10(np.clip(lin, OD_FLOOR, 1.0))
    od_full = (t[:, None] * od).sum(axis=0) / float((t * t).sum())
    rgb = np.clip(od_to_rgb(od_full) * 255.0, 0, 255)
    return tuple(int(round(v)) for v in rgb)
