"""Сборка слоёв обратно (Multiply) и метрика ошибки."""
import numpy as np

from .color import delta_e, od_to_rgb


def composite(t, paints_od):
    """Слои (P, H, W) со значениями [0..1] -> итоговое изображение sRGB uint8 (H, W, 3).
    Плотности слоёв складываются, что эквивалентно Multiply на белой бумаге."""
    od = np.tensordot(t, paints_od, axes=([0], [0]))  # (H, W, 3)
    return np.rint(od_to_rgb(od) * 255).astype(np.uint8)


def error_report(original_rgb, result_rgb):
    de = delta_e(original_rgb / 255.0, result_rgb / 255.0)
    rmse = float(np.sqrt(np.mean((original_rgb.astype(np.float32) - result_rgb) ** 2)))
    return {
        "dE_mean": float(de.mean()),
        "dE_median": float(np.median(de)),
        "dE_p95": float(np.percentile(de, 95)),
        "rmse_rgb": rmse,
    }
