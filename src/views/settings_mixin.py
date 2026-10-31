"""Наборы красок и пресеты настроек для главного окна (миксин MainWindow)."""
from pathlib import Path

from PyQt5.QtWidgets import (QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QMessageBox, QPushButton,
                             QVBoxLayout)

from core.library import paint_from_dict, paint_to_dict, safe_filename
from core.presets import image_path_for_storage, list_presets, read_preset, resolve_image_path, write_preset
from views.paints_dialog import PaintsDialog
from views.preset_dialog import PresetSaveDialog

ADHOC = "\x00adhoc"  # «набор из пресета»: его нет в библиотеке, он хранится внутри пресета
JSON_FILTER = "Пресеты AquaGraph (*.json);;Все файлы (*)"
DEFAULT_IMAGE = Path(__file__).resolve().parents[2] / "img" / "00091-3500186754.png"


class SettingsMixin:
    # ------------------------------------------------------------ наборы красок

    def current_set_label(self):
        key = self.cb_set.currentData()
        return self.adhoc_name if key == ADHOC else (key or "set")

    def paints_for_key(self, key):
        if key == ADHOC:
            return list(self.adhoc_paints or [])
        found = self.library.get_set(key)
        return list(found.paints) if found else []

    def refresh_set_combo(self, select=None):
        current = select or self.cb_set.currentData()
        self.cb_set.blockSignals(True)
        self.cb_set.clear()
        for s in self.library.sets():
            self.cb_set.addItem(s.name if s.builtin else "★ " + s.name, s.name)
        if self.adhoc_paints:
            self.cb_set.addItem("● %s (из пресета)" % self.adhoc_name, ADHOC)
        self.cb_set.setCurrentIndex(max(self.cb_set.findData(current), 0))
        self.cb_set.blockSignals(False)
        self._update_set_buttons()

    def _update_set_buttons(self):
        key = self.cb_set.currentData()
        self.btn_del_set.setEnabled(key in self.library.user_sets)

    def on_set_changed(self, *_):
        self._update_set_buttons()
        self.schedule_calc()

    def open_paints_dialog(self):
        key = self.cb_set.currentData()
        dialog = PaintsDialog(self.library, key if key != ADHOC else None, self)
        dialog.exec_()
        if dialog.saved_set_name:
            self.refresh_set_combo(select=dialog.saved_set_name)
            self.layers, self.set_key = [], None  # состав набора мог измениться
            self.start_calc()
        else:
            self.refresh_set_combo()

    def save_current_as_set(self):
        if not self.layers:
            QMessageBox.information(self, "Набор", "Нет слоёв: сначала загрузите фото.")
            return
        key = self.cb_set.currentData()
        default = key if key in self.library.user_sets else ""
        name, ok = QInputDialog.getText(self, "Сохранить как набор",
                                        "Название набора (порядок и колеры слоёв сохранятся):", text=default)
        name = name.strip()
        if not ok or not name:
            return
        if name in self.library.user_sets and QMessageBox.question(
                self, "Набор", "Набор «%s» уже есть. Заменить?" % name) != QMessageBox.Yes:
            return
        try:
            self.library.save_set(name, [l.paint for l in self.layers])
        except ValueError as exc:
            QMessageBox.warning(self, "Набор", str(exc))
            return
        self.set_key = name  # слои уже соответствуют набору, пересчёт не нужен
        self.refresh_set_combo(select=name)
        self.lbl_status.setText("Набор «%s» сохранён" % name)

    def delete_set(self):
        name = self.cb_set.currentData()
        if name not in self.library.user_sets:
            return
        if QMessageBox.question(self, "Удалить набор", "Удалить набор «%s»?" % name) != QMessageBox.Yes:
            return
        self.library.delete_set(name)
        self.refresh_set_combo(select="6 — классика")
        self.start_calc()

    # ------------------------------------------------------------ пресеты: интерфейс

    def _build_presets_group(self):
        g = QGroupBox("Пресеты настроек")
        box = QVBoxLayout(g)
        self.cb_preset = QComboBox()
        self.cb_preset.setToolTip("Пресеты лежат в папке presets рядом с программой")
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        for text, slot, tip in (
                ("Загрузить", self.load_selected_preset, "Применить выбранный пресет"),
                ("Сохранить…", self.save_preset, "Сохранить текущие настройки в папку presets"),
                ("Удалить", self.delete_preset, None)):
            b = QPushButton(text)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            row1.addWidget(b)
        for text, slot, tip in (
                ("Из файла…", self.load_preset_file, "Открыть пресет из любого места"),
                ("В файл…", self.save_preset_file, "Сохранить пресет в любое место (чтобы передать другому)"),
                ("По умолчанию", self.reset_to_defaults, "Вернуть все настройки к значениям первого запуска")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row2.addWidget(b)
        box.addWidget(self.cb_preset)
        box.addLayout(row1)
        box.addLayout(row2)
        return g

    def refresh_presets(self, select=None):
        self.cb_preset.clear()
        self.cb_preset.addItems(list_presets(self.preset_dir))
        if select:
            self.cb_preset.setCurrentText(select)

    # ------------------------------------------------------------ пресеты: действия

    def save_preset(self):
        dialog = PresetSaveDialog(self.cb_preset.currentText(), self.source_path is not None, True, self)
        if not dialog.exec_():
            return
        name = dialog.name
        if not name or name.startswith("_"):
            QMessageBox.information(self, "Пресет", "Введите название (не должно начинаться с «_»).")
            return
        path = self.preset_dir / (safe_filename(name) + ".json")
        if path.exists() and QMessageBox.question(
                self, "Пресет", "Пресет «%s» уже есть. Заменить?" % name) != QMessageBox.Yes:
            return
        self._write(path, name, dialog.include_image)
        self.refresh_presets(select=path.stem)

    def save_preset_file(self):
        dialog = PresetSaveDialog("", self.source_path is not None, False, self)
        if not dialog.exec_():
            return
        start = str(self.preset_dir / "preset.json")
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить пресет в файл", start, JSON_FILTER)
        if path:
            self._write(Path(path), Path(path).stem, dialog.include_image)
            self.refresh_presets()

    def _write(self, path, name, include_image):
        try:
            write_preset(path, {"name": name, **self.collect_settings(include_image)})
        except OSError as exc:
            QMessageBox.warning(self, "Пресет", "Не удалось сохранить: %s" % exc)
            return
        self.lbl_status.setText("Пресет сохранён: %s" % path)

    def load_selected_preset(self):
        name = self.cb_preset.currentText()
        if name:
            self._load_file(self.preset_dir / (name + ".json"))

    def load_preset_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть пресет", str(self.preset_dir), JSON_FILTER)
        if path:
            self._load_file(Path(path))

    def delete_preset(self):
        name = self.cb_preset.currentText()
        path = self.preset_dir / (name + ".json")
        if name and path.exists() and QMessageBox.question(
                self, "Удалить пресет", "Удалить пресет «%s»?" % name) == QMessageBox.Yes:
            path.unlink()
            self.refresh_presets()

    def _load_file(self, path):
        try:
            self.apply_settings(read_preset(path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Пресет", "Не удалось применить «%s»:\n%s" % (Path(path).name, exc))
            return
        self.lbl_status.setText("Пресет применён: %s" % Path(path).stem)

    # ------------------------------------------------------------ пресеты: содержимое

    def collect_settings(self, include_image):
        paints = [l.paint for l in self.layers] or self.paints_for_key(self.cb_set.currentData())
        data = {
            "set": {"name": self.current_set_label(), "paints": [paint_to_dict(p) for p in paints]},
            "layers": [{"id": l.paint.id, "visible": l.visible, "opacity": round(l.opacity, 3)} for l in self.layers],
            "calc": {
                "max_side": self.sp_side.value(), "levels": self.sp_levels.value(),
                "clusters": self.sp_clusters.value(), "max_paints": self.sp_paints.value(),
                "lam_paint": self.sp_lam_paint.value(), "lam_density": self.sp_lam_dens.value(),
                "smooth": self.sp_sr.value(), "boundary_sigma": self.sp_bsigma.value(),
                "min_area_percent": self.sp_area.value(), "auto": self.chk_auto.isChecked(),
                "feather_percent": self.sp_feather.value(), "edge_threshold": self.sp_edge.value(),
            },
            "outline": {
                "regions": self.chk_regions.isChecked(), "photo": self.chk_photo.isChecked(),
                "thickness": self.sp_thick.value(), "photo_threshold": self.sl_edge.value(),
                "color": list(self.outline_color), "show": self.chk_show_outline.isChecked(),
            },
            "export": {
                "width_mm": self.sp_w.value(), "dpi": self.sp_dpi.value(), "white_background": self.chk_white.isChecked(),
                "marks": self.chk_marks.isChecked(), "marks_inset_mm": self.sp_inset.value(),
            },
            "view": {"mode": self.cb_mode.currentText(), "split": self.sl_split.value()},
        }
        if include_image and self.source_path:
            data["image"] = image_path_for_storage(self.source_path, self.root_dir)
        return data

    @staticmethod
    def _put(widget, value):
        """Выставляет значение виджета без запуска пересчёта; отсутствующее значение пропускается."""
        if value is None:
            return
        widget.blockSignals(True)
        try:
            if hasattr(widget, "setChecked"):
                widget.setChecked(bool(value))
            elif hasattr(widget, "setCurrentText"):
                widget.setCurrentText(str(value))
            else:
                widget.setValue(value)
        finally:
            widget.blockSignals(False)

    def apply_settings(self, data):
        calc, outline = data.get("calc", {}), data.get("outline", {})
        export, view = data.get("export", {}), data.get("view", {})
        put = self._put

        put(self.sp_side, calc.get("max_side"))
        put(self.sp_levels, calc.get("levels"))
        put(self.sp_clusters, calc.get("clusters"))
        put(self.sp_paints, calc.get("max_paints"))
        put(self.sp_lam_paint, calc.get("lam_paint"))
        put(self.sp_lam_dens, calc.get("lam_density"))
        put(self.sp_sr, calc.get("smooth"))
        put(self.sp_bsigma, calc.get("boundary_sigma"))
        put(self.sp_area, calc.get("min_area_percent"))
        put(self.sp_feather, calc.get("feather_percent"))
        put(self.sp_edge, calc.get("edge_threshold"))
        put(self.chk_auto, calc.get("auto"))

        put(self.chk_regions, outline.get("regions"))
        put(self.chk_photo, outline.get("photo"))
        put(self.sp_thick, outline.get("thickness"))
        put(self.sl_edge, outline.get("photo_threshold"))
        put(self.chk_show_outline, outline.get("show"))
        if outline.get("color"):
            self.outline_color = tuple(int(c) for c in outline["color"][:3])
            self._paint_outline_button()

        put(self.sp_w, export.get("width_mm"))
        put(self.sp_dpi, export.get("dpi"))
        put(self.chk_white, export.get("white_background"))
        put(self.chk_marks, export.get("marks"))
        put(self.sp_inset, export.get("marks_inset_mm"))
        put(self.cb_mode, view.get("mode"))
        put(self.sl_split, view.get("split"))
        self._link_size(True)

        saved_set = data.get("set") or {}
        if saved_set.get("paints"):
            paints = [paint_from_dict(p) for p in saved_set["paints"]]
            name = saved_set.get("name") or "без названия"
            existing = self.library.get_set(name)
            same = existing and [(p.id, tuple(p.rgb)) for p in existing.paints] == [(p.id, tuple(p.rgb)) for p in paints]
            if same:
                self.adhoc_paints = None
                self.refresh_set_combo(select=name)
            else:
                self.adhoc_paints, self.adhoc_name = paints, name
                self.refresh_set_combo(select=ADHOC)
        self.pending_layer_state = data.get("layers")
        self.layers, self.set_key = [], None

        image = data.get("image")
        if image:
            path = resolve_image_path(image, self.root_dir)
            if path.exists():
                self.load_image(str(path))
                return
            QMessageBox.warning(self, "Пресет", "Фото из пресета не найдено:\n%s\nПрименены остальные настройки." % path)
        if self.original is not None:
            self.prepare_image()
        self.render()

    def apply_pending_layer_state(self):
        state = {s.get("id"): s for s in (self.pending_layer_state or [])}
        for layer in self.layers:
            s = state.get(layer.paint.id)
            if s:
                layer.visible = bool(s.get("visible", True))
                layer.opacity = min(max(float(s.get("opacity", 1.0)), 0.0), 1.0)
        self.pending_layer_state = None

    # ------------------------------------------------------------ запуск и закрытие

    def load_startup_image(self):
        if DEFAULT_IMAGE.exists():
            self.load_image(str(DEFAULT_IMAGE))

    def reset_to_defaults(self):
        """Возвращает все настройки к значениям при первом запуске (фото остаётся)."""
        try:
            self.apply_settings(self.default_settings)
        except (ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Сброс", str(exc))
            return
        self.lbl_status.setText("Настройки сброшены по умолчанию")

    def closeEvent(self, event):
        if self.thread is not None:
            self.thread.wait(10000)
        super().closeEvent(event)
