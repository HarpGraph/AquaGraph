"""Разложение изображения на слои красок.

Пайплайн:  фото -> регионы (k-means в Lab + сглаживание границ) ->
для каждого региона лучший достижимый «рецепт» (≤ max_paints красок, густота на ступенях) ->
слои (P, H, W), уже квантованные и состоящие из цельных пятен.
"""
import itertools
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.spatial import cKDTree

from .color import delta_e, od_to_rgb, rgb_to_lab, rgb_to_od


# ---------------------------------------------------------------- рецепты

def build_recipes(paints_od, levels=4, max_paints=3):
    """Все достижимые комбинации красок/ступеней.

    Возвращает (steps (C, P) uint8 — номера ступеней 0..levels, rgb (C, 3) float32 sRGB [0..1]).
    Первая строка — чистая бумага."""
    n_paints = len(paints_od)
    rows = [np.zeros((1, n_paints), dtype=np.uint8)]
    for k in range(1, min(max_paints, n_paints) + 1):
        grid = np.array(list(itertools.product(range(1, levels + 1), repeat=k)), dtype=np.uint8)
        for subset in itertools.combinations(range(n_paints), k):
            block = np.zeros((len(grid), n_paints), dtype=np.uint8)
            block[:, list(subset)] = grid
            rows.append(block)
    steps = np.concatenate(rows)
    od = (steps.astype(np.float32) / levels) @ paints_od
    return steps, od_to_rgb(od)


def best_recipes(colors, steps, recipe_rgb, levels, lam_paint=0.5, lam_density=0.5):
    """Индекс лучшего рецепта для каждого цвета (M, 3 sRGB [0..1]).

    cost = ΔE(Lab) + lam_paint * число красок + lam_density * суммарная густота."""
    recipe_lab = rgb_to_lab(recipe_rgb)
    penalty = (
        lam_paint * np.count_nonzero(steps, axis=1)
        + lam_density * steps.sum(axis=1) / levels
    ).astype(np.float32)
    target_lab = rgb_to_lab(np.asarray(colors, dtype=np.float32))
    result = np.empty(len(target_lab), dtype=np.int64)
    chunk = 16
    for s in range(0, len(target_lab), chunk):
        d = np.linalg.norm(target_lab[s:s + chunk, None, :] - recipe_lab[None, :, :], axis=2)
        result[s:s + chunk] = np.argmin(d + penalty[None, :], axis=1)
    return result


# ---------------------------------------------------------------- регионы

def segment(image_rgb, clusters=48, smooth_sp=6, smooth_sr=14, boundary_sigma=2.0,
            min_area_frac=0.0003, sample=60000, seed=0):
    """Фото -> (labels (H, W) int32, mean_colors (K, 3) sRGB [0..1], smooth (H, W, 3) sRGB [0..1])."""
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    if smooth_sp > 0:
        bgr = cv2.pyrMeanShiftFiltering(bgr, smooth_sp, smooth_sr, maxLevel=1)
    smooth = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    h, w = smooth.shape[:2]

    lab = rgb_to_lab(smooth).reshape(-1, 3)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(lab), size=min(sample, len(lab)), replace=False)
    cv2.setRNGSeed(seed)
    _, _, centers = cv2.kmeans(
        np.ascontiguousarray(lab[pick]), clusters, None,
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5), 3, cv2.KMEANS_PP_CENTERS,
    )
    labels = cKDTree(centers).query(lab)[1].astype(np.int32).reshape(h, w)

    if boundary_sigma > 0:
        labels = _smooth_labels(labels, boundary_sigma)
    labels = _drop_small_regions(labels, max(4, int(min_area_frac * h * w)))

    flat = labels.reshape(-1)
    counts = np.maximum(np.bincount(flat, minlength=clusters), 1)
    colors = np.stack(
        [np.bincount(flat, weights=smooth[..., c].reshape(-1), minlength=clusters) / counts for c in range(3)],
        axis=1,
    ).astype(np.float32)
    return labels, colors, smooth


def sharp_edges(smooth_rgb01, threshold=2.0, sigma=1.2):
    """Маска настоящих краёв на фото: где цвет меняется быстрее `threshold` ΔE на пиксель."""
    lab = cv2.GaussianBlur(rgb_to_lab(smooth_rgb01), (0, 0), sigma)
    grad2 = sum(
        cv2.Sobel(lab[..., c], cv2.CV_32F, 1, 0, ksize=3) ** 2 + cv2.Sobel(lab[..., c], cv2.CV_32F, 0, 1, ksize=3) ** 2
        for c in range(3)
    )
    return (np.sqrt(grad2) / 8.0) > threshold


def soften_layers(layers, smooth_rgb01, feather, edge_threshold=2.0):
    """Плавные переходы только там, где плавный переход есть на самом фото.

    Слои размываются на `feather` пикселей, но вблизи настоящих краёв остаются резкими —
    так сглаживается «ступенчатость» градиентов и не мылятся границы предметов."""
    blurred = np.stack([cv2.GaussianBlur(layer, (0, 0), feather) for layer in layers])
    edges = sharp_edges(smooth_rgb01, edge_threshold).astype(np.float32)
    radius = int(np.ceil(feather * 1.5))
    near_edge = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1)))
    keep_sharp = np.clip(cv2.GaussianBlur(near_edge, (0, 0), max(feather * 0.5, 0.5)), 0.0, 1.0)
    return layers * keep_sharp + blurred * (1.0 - keep_sharp)


def _smooth_labels(labels, sigma):
    """Сглаживание границ: размытие маски каждого региона и выбор максимума."""
    best = np.full(labels.shape, -1.0, dtype=np.float32)
    out = labels.copy()
    for c in np.unique(labels):
        score = cv2.GaussianBlur((labels == c).astype(np.float32), (0, 0), sigma)
        better = score > best
        best[better] = score[better]
        out[better] = c
    return out


def _drop_small_regions(labels, min_area):
    """Мелкие связные пятна заменяются преобладающей меткой вокруг."""
    labels = labels.copy()
    kernel = np.ones((3, 3), np.uint8)
    for c in np.unique(labels):
        mask = (labels == c).astype(np.uint8)
        n, comp, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                continue
            x, y, bw, bh = stats[i, :4]
            x0, y0 = max(x - 2, 0), max(y - 2, 0)
            window = (slice(y0, y + bh + 2), slice(x0, x + bw + 2))
            inside = comp[window] == i
            ring = cv2.dilate(inside.astype(np.uint8), kernel).astype(bool) & ~inside
            around = labels[window][ring]
            if around.size:
                labels[window][inside] = np.bincount(around).argmax()
    return labels


# ---------------------------------------------------------------- сборка слоёв

@dataclass
class Decomposition:
    layers: np.ndarray      # (P, H, W) float32, значения k/levels
    recipe_map: np.ndarray  # (H, W) int32: номер рецепта пикселя (границы = границы пятен краски)


def decompose_full(image_rgb, paints_od, levels=4, max_paints=3, clusters=48,
                   lam_paint=0.5, lam_density=0.5, feather=0.0, edge_threshold=2.0, **segment_kwargs):
    """Фото (H, W, 3 uint8) -> Decomposition.

    feather — на сколько пикселей размывать переходы слоёв (0 — выключено). Размытие
    учитывает края фото: резкие границы остаются резкими (edge_threshold — чувствительность,
    ΔE на пиксель: меньше — больше краёв сохраняется). recipe_map (а значит и контур) всегда чёткий."""
    labels, colors, smooth = segment(image_rgb, clusters=clusters, **segment_kwargs)
    steps, recipe_rgb = build_recipes(paints_od, levels, max_paints)
    pick = best_recipes(colors, steps, recipe_rgb, levels, lam_paint, lam_density)
    per_label = steps[pick].astype(np.float32) / levels  # (K, P)
    layers = np.ascontiguousarray(per_label[labels].transpose(2, 0, 1))
    if feather > 0:
        layers = soften_layers(layers, smooth, feather, edge_threshold)
    return Decomposition(layers, pick[labels].astype(np.int32))


def decompose(image_rgb, paints_od, **kwargs):
    """То же, но возвращает только слои (P, H, W)."""
    return decompose_full(image_rgb, paints_od, **kwargs).layers


# ---------------------------------------------------------------- непрерывное решение (эталон)

def unmix_colors(colors, paints_od, max_paints=3, tmax=1.0, lam_paint=2.0, lam_density=2.0):
    """Непрерывная густота красок для набора цветов (M, 3) -> (M, P).

    МНК в плотности по каждому подмножеству красок + отсечение [0..tmax].
    Нужен как эталон «лучшее, что даёт набор без квантования»."""
    colors = np.asarray(colors, dtype=np.float32)
    n_paints = len(paints_od)
    target_od = rgb_to_od(colors)

    best_cost = delta_e(np.ones_like(colors), colors).astype(np.float32)
    best_t = np.zeros((len(colors), n_paints), dtype=np.float32)
    for k in range(1, min(max_paints, n_paints) + 1):
        for subset in itertools.combinations(range(n_paints), k):
            idx = list(subset)
            a = paints_od[idx].T
            t = np.clip(target_od @ np.linalg.pinv(a, rcond=1e-3).T, 0.0, tmax)
            cost = (
                delta_e(od_to_rgb(t @ a.T), colors)
                + lam_paint * np.count_nonzero(t > 1e-3, axis=1) + lam_density * t.sum(1)
            )
            better = cost < best_cost
            if better.any():
                best_cost[better] = cost[better]
                best_t[better] = 0.0
                best_t[np.ix_(better, idx)] = t[better]
    return best_t
