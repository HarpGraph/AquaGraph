"""Библиотека красок и готовые наборы."""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .color import rgb_to_lab, rgb_to_od

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "palettes" / "default.json"


@dataclass(frozen=True)
class Paint:
    id: str
    name_ru: str
    name_en: str
    rgb: tuple

    @property
    def rgb01(self):
        return np.array(self.rgb, dtype=np.float32) / 255.0

    @property
    def od(self):
        return rgb_to_od(self.rgb01)

    @property
    def lightness(self):
        return float(rgb_to_lab(self.rgb01)[0])


def load_library(path=DEFAULT_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    paints = {p["id"]: Paint(p["id"], p["name_ru"], p["name_en"], tuple(p["rgb"])) for p in data["paints"]}
    return paints, data["sets"]


def get_set(name, path=DEFAULT_PATH, sort_by_lightness=True):
    """Набор красок, по умолчанию упорядоченный от светлых к тёмным."""
    paints, sets = load_library(path)
    result = [paints[pid] for pid in sets[str(name)]]
    if sort_by_lightness:
        result.sort(key=lambda p: -p.lightness)
    return result


def paints_od(paints):
    return np.stack([p.od for p in paints]).astype(np.float32)
