"""Цветовая математика: sRGB <-> линейный свет <-> оптическая плотность, Lab, ΔE."""
import cv2
import numpy as np

OD_FLOOR = 0.004  # минимальная линейная яркость: глубже чёрного краской не получить


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float32), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055).astype(np.float32)


def rgb_to_od(rgb01):
    """sRGB [0..1] -> оптическая плотность по каналам (Beer–Lambert в линейном свете)."""
    lin = np.maximum(srgb_to_linear(rgb01), OD_FLOOR)
    return (-np.log10(lin)).astype(np.float32)


def od_to_rgb(od):
    """Оптическая плотность -> sRGB [0..1]."""
    return linear_to_srgb(np.power(10.0, -np.asarray(od, dtype=np.float32)))


def rgb_to_lab(rgb01):
    """sRGB [0..1], форма (..., 3) -> Lab (L 0..100)."""
    arr = np.asarray(rgb01, dtype=np.float32)
    a = np.ascontiguousarray(arr.reshape(-1, 1, 3))
    return cv2.cvtColor(a, cv2.COLOR_RGB2Lab).reshape(arr.shape)


def delta_e(rgb_a, rgb_b):
    """ΔE76 между двумя наборами sRGB [0..1]."""
    return np.linalg.norm(rgb_to_lab(rgb_a) - rgb_to_lab(rgb_b), axis=-1)
