"""Контурный слой для карандашного наброска."""
import cv2
import numpy as np


def region_outline(recipe_map, thickness=2.0):
    """Линии по границам пятен краски. Возвращает маску (H, W) float32 [0..1]."""
    rm = recipe_map
    edge = np.zeros(rm.shape, dtype=np.uint8)
    edge[:, :-1] |= (rm[:, :-1] != rm[:, 1:])
    edge[:-1, :] |= (rm[:-1, :] != rm[1:, :])
    return _thicken(edge, thickness)


def photo_edges(image_rgb, low=40, high=110, blur=1.5, min_len_frac=0.02, thickness=2.0):
    """Контуры по самому фото (Canny), короткие обрывки отбрасываются."""
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    if blur > 0:
        gray = cv2.GaussianBlur(gray, (0, 0), blur)
    edges = cv2.Canny(gray, low, high)
    min_len = int(min_len_frac * max(edges.shape))
    n, comp, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = np.maximum(stats[1:, cv2.CC_STAT_WIDTH], stats[1:, cv2.CC_STAT_HEIGHT]) >= min_len
    return _thicken((keep[comp]).astype(np.uint8), thickness)


def _thicken(edge01, thickness):
    mask = edge01.astype(np.float32)
    if thickness > 1.0:
        k = int(round(thickness)) | 1
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return np.clip(cv2.GaussianBlur(mask, (0, 0), 0.6), 0.0, 1.0)


def build_outline(recipe_map, image_rgb, use_regions=True, use_photo=False, thickness=2.0, photo_threshold=110):
    """Итоговая маска контура (H, W) float32 или None, если ничего не выбрано."""
    parts = []
    if use_regions and recipe_map is not None:
        parts.append(region_outline(recipe_map, thickness))
    if use_photo and image_rgb is not None:
        parts.append(photo_edges(image_rgb, low=photo_threshold * 0.4, high=photo_threshold, thickness=thickness))
    return np.maximum.reduce(parts) if parts else None
