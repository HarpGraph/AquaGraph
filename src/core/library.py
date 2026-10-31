"""Библиотека красок: заводские краски и наборы + свои краски и наборы пользователя.

Заводские данные (palettes/default.json) не меняются. Своё хранится в palettes/user.json.
Набор хранит собственные копии красок, поэтому правка краски в библиотеке не меняет
уже сохранённые наборы, а набор можно целиком перенести на другой компьютер."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .palettes import DEFAULT_PATH, Paint

USER_PATH = DEFAULT_PATH.with_name("user.json")
FACTORY_SET_TITLES = {
    "3": "3 — триада", "4": "4 — минимум", "6": "6 — классика", "9": "9 — расширенный", "12": "12 — студийный",
}
MIN_SET, MAX_SET = 3, 12


@dataclass
class PaintSet:
    name: str
    paints: list
    builtin: bool


def paint_to_dict(p):
    return {"id": p.id, "name_ru": p.name_ru, "name_en": p.name_en, "rgb": list(p.rgb)}


def paint_from_dict(d):
    rgb = tuple(max(0, min(255, int(v))) for v in d["rgb"][:3])
    if len(rgb) != 3:
        raise ValueError("rgb must have 3 components")
    return Paint(str(d["id"]), str(d.get("name_ru") or d.get("name_en") or d["id"]),
                 str(d.get("name_en") or d.get("name_ru") or d["id"]), rgb)


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "paint"


def safe_filename(text):
    """Имя, пригодное для файла/папки Windows."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text).strip(" .")
    return cleaned or "unnamed"


class PaintLibrary:
    def __init__(self, factory_path=DEFAULT_PATH, user_path=USER_PATH):
        self.user_path = Path(user_path)
        data = json.loads(Path(factory_path).read_text(encoding="utf-8"))
        self.factory_paints = [paint_from_dict(p) for p in data["paints"]]
        by_id = {p.id: p for p in self.factory_paints}
        self._factory_sets = {}
        for key, ids in data["sets"].items():
            paints = sorted((by_id[i] for i in ids), key=lambda p: -p.lightness)
            self._factory_sets[FACTORY_SET_TITLES.get(key, key)] = paints
        self.user_paints = []
        self.user_sets = {}
        self._load_user()

    # ---------------------------------------------------------- хранение

    def _load_user(self):
        if not self.user_path.exists():
            return
        try:
            data = json.loads(self.user_path.read_text(encoding="utf-8"))
            self.user_paints = [paint_from_dict(p) for p in data.get("paints", [])]
            self.user_sets = {
                name: [paint_from_dict(p) for p in paints] for name, paints in data.get("sets", {}).items()
            }
        except (ValueError, KeyError, TypeError):
            # повреждённый файл не должен ломать запуск: сохраняем копию и начинаем с чистого листа
            self.user_path.replace(self.user_path.with_suffix(".broken.json"))
            self.user_paints, self.user_sets = [], {}

    def save(self):
        data = {
            "paints": [paint_to_dict(p) for p in self.user_paints],
            "sets": {n: [paint_to_dict(p) for p in ps] for n, ps in self.user_sets.items()},
        }
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------------- краски

    @property
    def paints(self):
        return self.factory_paints + self.user_paints

    def get_paint(self, paint_id):
        return next((p for p in self.paints if p.id == paint_id), None)

    def is_user_paint(self, paint_id):
        return any(p.id == paint_id for p in self.user_paints)

    def unique_id(self, base):
        taken = {p.id for p in self.paints}
        base = slugify(base)
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = "%s_%d" % (base, n), n + 1
        return candidate

    def add_paint(self, name_ru, name_en, rgb, save=True):
        paint = Paint(self.unique_id(name_en or name_ru), name_ru, name_en, tuple(rgb))
        self.user_paints.append(paint)
        if save:
            self.save()
        return paint

    def update_paint(self, paint_id, **fields):
        """Менять можно только свои краски. Возвращает обновлённую краску."""
        for i, p in enumerate(self.user_paints):
            if p.id == paint_id:
                new = Paint(p.id, fields.get("name_ru", p.name_ru), fields.get("name_en", p.name_en),
                            tuple(fields.get("rgb", p.rgb)))
                self.user_paints[i] = new
                self.save()
                return new
        raise KeyError(paint_id)

    def delete_paint(self, paint_id):
        before = len(self.user_paints)
        self.user_paints = [p for p in self.user_paints if p.id != paint_id]
        if len(self.user_paints) == before:
            raise KeyError(paint_id)
        self.save()

    # ---------------------------------------------------------- наборы

    def sets(self):
        factory = [PaintSet(n, list(ps), True) for n, ps in self._factory_sets.items()]
        mine = [PaintSet(n, list(ps), False) for n, ps in sorted(self.user_sets.items(), key=lambda kv: kv[0].lower())]
        return factory + mine

    def get_set(self, name):
        return next((s for s in self.sets() if s.name == name), None)

    def is_builtin_set(self, name):
        return name in self._factory_sets

    def save_set(self, name, paints):
        name = name.strip()
        if not name:
            raise ValueError("Название набора пустое")
        if self.is_builtin_set(name):
            raise ValueError("Это название занято заводским набором")
        if not MIN_SET <= len(paints) <= MAX_SET:
            raise ValueError("В наборе должно быть от %d до %d красок" % (MIN_SET, MAX_SET))
        self.user_sets[name] = list(paints)
        self.save()

    def delete_set(self, name):
        if name not in self.user_sets:
            raise KeyError(name)
        del self.user_sets[name]
        self.save()
