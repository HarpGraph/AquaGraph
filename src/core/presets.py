"""Пресеты общих настроек программы: обычные JSON-файлы (можно переносить и делиться)."""
import json
from pathlib import Path

PRESET_VERSION = 1


def list_presets(folder):
    """Имена пресетов (без расширения); служебные, начинающиеся с «_», не показываются."""
    folder = Path(folder)
    if not folder.exists():
        return []
    return sorted((p.stem for p in folder.glob("*.json") if not p.stem.startswith("_")), key=str.lower)


def write_preset(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": PRESET_VERSION, **data}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_preset(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Файл не похож на пресет AquaGraph")
    return data


def image_path_for_storage(path, root):
    """Путь внутри папки проекта хранится относительным — пресет переживает перенос проекта."""
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_image_path(stored, root):
    p = Path(stored)
    return p if p.is_absolute() else Path(root) / p
