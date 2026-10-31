"""Главное окно AquaGraph."""
import dataclasses
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                             QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from core.compose import composite, error_report
from core.export import MM_PER_INCH, OUTLINE_COLOR, export_layer_set, mm_to_px, registration_marks
from core.library import PaintLibrary, safe_filename, slugify
from core.outline import build_outline
from core.palettes import paints_od
from core.unmix import decompose_full
from views.image_view import ImageView
from views.layers_panel import Layer, LayersPanel
from views.settings_mixin import SettingsMixin

ROOT = Path(__file__).resolve().parents[2]
IMAGE_FILTER = "Изображения (*.png *.jpg *.jpeg *.bmp *.webp);;Все файлы (*)"
VIEW_MODES = ["Результат", "Оригинал", "Сравнение", "Выбранный слой"]


class CalcThread(QThread):
    done = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, image, od, params, ids):
        super().__init__()
        self.image, self.od, self.params, self.ids = image, od, params, ids

    def run(self):
        try:
            self.done.emit(decompose_full(self.image, self.od, **self.params), self.ids)
        except Exception as exc:  # показываем пользователю, а не роняем окно
            self.failed.emit(str(exc))


def _spin(lo, hi, value, step=1, decimals=None, suffix=""):
    w = QSpinBox() if decimals is None else QDoubleSpinBox()
    w.setRange(lo, hi)
    if decimals is not None:
        w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setValue(value)
    if suffix:
        w.setSuffix(suffix)
    return w


class MainWindow(SettingsMixin, QMainWindow):
    def __init__(self, library=None, preset_dir=None):
        super().__init__()
        self.setWindowTitle("AquaGraph — акварельные слои для Quest")
        self.resize(1500, 900)
        self.setAcceptDrops(True)

        self.library = library or PaintLibrary()
        self.preset_dir = Path(preset_dir) if preset_dir else ROOT / "presets"
        self.source = None          # PIL.Image исходного фото
        self.source_path = None
        self.source_name = "image"
        self.original = None        # рабочее изображение (H, W, 3 uint8)
        self.layers = []
        self.set_key = None         # набор, по которому построены слои
        self.adhoc_paints = None    # набор из пресета, которого нет в библиотеке
        self.adhoc_name = ""
        self.root_dir = ROOT
        self.pending_layer_state = None
        self.recipe_map = None
        self.outline = None
        self.outline_color = OUTLINE_COLOR
        self.selected = 0
        self.thread = None
        self.pending = False

        self.recalc_timer = QTimer(self, singleShot=True, interval=450)
        self.recalc_timer.timeout.connect(self.start_calc)

        splitter = QSplitter()
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        self.layers_panel = LayersPanel()
        self.layers_panel.changed.connect(self.render)
        self.layers_panel.selected.connect(self.select_layer)
        self.layers_panel.reorder.connect(self.reorder_layer)
        self.layers_panel.pick_color.connect(self.change_color)
        splitter.addWidget(self.layers_panel)
        splitter.setSizes([330, 880, 290])
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.refresh_set_combo(select="6 — классика")
        self.refresh_presets()
        self.default_settings = self.collect_settings(False)
        self.load_startup_image()

    # ------------------------------------------------------------ интерфейс

    def _build_left(self):
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addWidget(self._build_presets_group())

        g = QGroupBox("Фото")
        f = QVBoxLayout(g)
        btn = QPushButton("Открыть фото…")
        btn.clicked.connect(self.open_image)
        self.lbl_file = QLabel("— (можно перетащить файл в окно)")
        self.lbl_file.setWordWrap(True)
        self.sp_side = _spin(300, 3000, 1000, 100, suffix=" px")
        self.sp_side.setToolTip("Длинная сторона рабочего изображения")
        self.sp_side.editingFinished.connect(self.prepare_image)
        row = QFormLayout()
        row.addRow("Рабочий размер:", self.sp_side)
        f.addWidget(btn)
        f.addWidget(self.lbl_file)
        f.addLayout(row)
        box.addWidget(g)

        g = QGroupBox("Краски")
        f = QFormLayout(g)
        self.cb_set = QComboBox()
        self.cb_set.currentIndexChanged.connect(self.on_set_changed)
        self.btn_del_set = QPushButton("Удалить набор")
        self.btn_del_set.clicked.connect(self.delete_set)
        btn_edit = QPushButton("Краски и наборы…")
        btn_edit.setToolTip("Библиотека красок: добавить свою краску, собрать свой набор")
        btn_edit.clicked.connect(self.open_paints_dialog)
        btn_save = QPushButton("Сохранить как набор…")
        btn_save.setToolTip("Сохранить текущие слои (порядок и колеры) как свой набор")
        btn_save.clicked.connect(self.save_current_as_set)
        f.addRow("Набор:", self.cb_set)
        f.addRow(btn_edit)
        f.addRow(btn_save)
        f.addRow(self.btn_del_set)
        box.addWidget(g)

        g = QGroupBox("Расчёт")
        f = QFormLayout(g)
        self.sp_levels = _spin(2, 8, 4)
        self.sp_levels.setToolTip("Сколько ступеней густоты у каждой краски")
        self.sp_clusters = _spin(8, 128, 48)
        self.sp_clusters.setToolTip("Сколько цветовых пятен выделять на картинке")
        self.sp_paints = _spin(1, 4, 3)
        self.sp_paints.setToolTip("Максимум красок в одном пятне (4 считается заметно дольше)")
        self.sp_lam_paint = _spin(0.0, 10.0, 0.5, 0.1, 1)
        self.sp_lam_paint.setToolTip("Штраф за каждую краску в смеси: больше — проще слои")
        self.sp_lam_dens = _spin(0.0, 10.0, 0.5, 0.1, 1)
        self.sp_lam_dens.setToolTip("Штраф за густоту: больше — светлее и экономнее")
        self.sp_sr = _spin(0, 40, 14)
        self.sp_sr.setToolTip("Сглаживание текстуры холста/зерна перед выделением пятен")
        self.sp_bsigma = _spin(0.0, 6.0, 2.0, 0.5, 1)
        self.sp_bsigma.setToolTip("Сглаживание границ пятен")
        self.sp_area = _spin(0.0, 2.0, 0.03, 0.01, 2, " %")
        self.sp_area.setToolTip("Пятна меньше этой доли кадра убираются")
        self.sp_feather = _spin(0.0, 3.0, 0.8, 0.1, 1, " %")
        self.sp_feather.setToolTip("Плавность переходов краски (в % от длинной стороны). 0 — резкие ступени, "
                                   "как у плоских пятен. Резкие края предметов остаются резкими.")
        self.sp_edge = _spin(0.5, 10.0, 2.0, 0.5, 1)
        self.sp_edge.setToolTip("Какие края считать резкими и не размывать. Меньше — резких краёв больше; "
                                "больше — размывается почти всё, кроме самых контрастных границ.")
        for label, w in (("Ступеней густоты:", self.sp_levels), ("Пятен цвета:", self.sp_clusters),
                         ("Красок в смеси:", self.sp_paints), ("Штраф за краску:", self.sp_lam_paint),
                         ("Штраф за густоту:", self.sp_lam_dens), ("Сглаживание текстуры:", self.sp_sr),
                         ("Сглаживание границ:", self.sp_bsigma), ("Мин. пятно:", self.sp_area),
                         ("Плавность переходов:", self.sp_feather), ("Резкость краёв:", self.sp_edge)):
            f.addRow(label, w)
            w.valueChanged.connect(self.schedule_calc)
        self.chk_auto = QCheckBox("Пересчитывать автоматически")
        self.chk_auto.setChecked(True)
        btn = QPushButton("Рассчитать")
        btn.clicked.connect(self.start_calc)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)
        f.addRow(self.chk_auto)
        f.addRow(btn)
        f.addRow(self.progress)
        box.addWidget(g)

        g = QGroupBox("Контур для карандаша")
        f = QFormLayout(g)
        self.chk_regions = QCheckBox("Границы пятен краски")
        self.chk_regions.setChecked(True)
        self.chk_photo = QCheckBox("Контуры самого фото")
        self.sp_thick = _spin(1.0, 8.0, 2.0, 0.5, 1, " px")
        self.sl_edge = QSlider(Qt.Horizontal)
        self.sl_edge.setRange(30, 250)
        self.sl_edge.setValue(110)
        self.sl_edge.setToolTip("Порог для контуров фото: больше — меньше линий")
        self.btn_ocolor = QPushButton()
        self.btn_ocolor.setFixedHeight(22)
        self.btn_ocolor.clicked.connect(self.change_outline_color)
        self._paint_outline_button()
        for w in (self.chk_regions, self.chk_photo):
            w.toggled.connect(self.update_outline)
        self.sp_thick.valueChanged.connect(self.update_outline)
        self.sl_edge.valueChanged.connect(self.update_outline)
        f.addRow(self.chk_regions)
        f.addRow(self.chk_photo)
        f.addRow("Толщина:", self.sp_thick)
        f.addRow("Порог фото:", self.sl_edge)
        f.addRow("Цвет линий:", self.btn_ocolor)
        box.addWidget(g)

        g = QGroupBox("Экспорт")
        f = QFormLayout(g)
        self.sp_w = _spin(10.0, 5000.0, 200.0, 10.0, 1, " мм")
        self.sp_h = _spin(10.0, 5000.0, 300.0, 10.0, 1, " мм")
        self.sp_dpi = _spin(30, 600, 150, 10, suffix=" dpi")
        self.lbl_px = QLabel()
        self.chk_white = QCheckBox("Слои на белом фоне (без прозрачности)")
        self.chk_marks = QCheckBox("Метки совмещения (⊕ в углах)")
        self.chk_marks.setToolTip("На каждом слое в углах листа: по ним слои в очках совмещаются с бумагой одинаково")
        self.sp_inset = _spin(2.0, 100.0, 8.0, 1.0, 1, " мм")
        self.sp_inset.setToolTip("Расстояние от центра метки до края листа")
        self.chk_marks.toggled.connect(self.render)
        self.sp_inset.valueChanged.connect(self.render)
        self.sp_w.valueChanged.connect(lambda v: self._link_size(True))
        self.sp_h.valueChanged.connect(lambda v: self._link_size(False))
        self.sp_dpi.valueChanged.connect(self._update_px_label)
        btn = QPushButton("Экспорт слоёв…")
        btn.clicked.connect(self.export)
        f.addRow("Ширина листа:", self.sp_w)
        f.addRow("Высота листа:", self.sp_h)
        f.addRow("Разрешение:", self.sp_dpi)
        f.addRow("Размер файла:", self.lbl_px)
        f.addRow(self.chk_marks)
        f.addRow("Отступ меток:", self.sp_inset)
        f.addRow(self.chk_white)
        f.addRow(btn)
        box.addWidget(g)
        box.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(310)
        return scroll

    def _build_center(self):
        w = QWidget()
        box = QVBoxLayout(w)
        box.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 6, 6, 0)
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(VIEW_MODES)
        self.cb_mode.currentIndexChanged.connect(self.render)
        self.chk_show_outline = QCheckBox("Контур")
        self.chk_show_outline.setChecked(True)
        self.chk_show_outline.toggled.connect(self.render)
        self.sl_split = QSlider(Qt.Horizontal)
        self.sl_split.setRange(0, 100)
        self.sl_split.setValue(50)
        self.sl_split.setMaximumWidth(220)
        self.sl_split.setToolTip("Граница «оригинал | результат»")
        self.sl_split.valueChanged.connect(self.render)
        self.lbl_err = QLabel()
        bar.addWidget(QLabel("Вид:"))
        bar.addWidget(self.cb_mode)
        bar.addWidget(self.sl_split)
        bar.addWidget(self.chk_show_outline)
        bar.addStretch(1)
        bar.addWidget(self.lbl_err)
        box.addLayout(bar)

        self.view = ImageView()
        box.addWidget(self.view, 1)
        self.lbl_status = QLabel("Колесо — масштаб, перетаскивание — сдвиг, двойной клик — вписать")
        self.lbl_status.setContentsMargins(6, 0, 6, 4)
        box.addWidget(self.lbl_status)
        return w

    def _paint_outline_button(self):
        self.btn_ocolor.setStyleSheet("background:%s; border:1px solid #222;" % QColor(*self.outline_color).name())

    # ------------------------------------------------------------ загрузка

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.load_image(urls[0].toLocalFile())

    def open_image(self):
        start = str(ROOT / "img") if (ROOT / "img").exists() else ""
        path, _ = QFileDialog.getOpenFileName(self, "Открыть фото", start, IMAGE_FILTER)
        if path:
            self.load_image(path)

    def load_image(self, path):
        try:
            self.source = Image.open(path).convert("RGB")
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось открыть", str(exc))
            return
        self.source_name = Path(path).stem
        self.source_path = str(path)
        self.layers, self.set_key = [], None
        self.prepare_image()

    def prepare_image(self):
        if self.source is None:
            return
        img = self.source
        scale = self.sp_side.value() / max(img.size)
        if scale < 1:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        if self.original is not None and self.original.shape[:2] == (img.height, img.width) and self.layers:
            return
        self.original = np.asarray(img)
        self.lbl_file.setText("%s\n%d × %d px (исходник %d × %d)" % (
            self.source_name, img.width, img.height, *self.source.size))
        self.sp_h.blockSignals(True)
        self.sp_h.setValue(round(self.sp_w.value() * img.height / img.width, 1))
        self.sp_h.blockSignals(False)
        self._update_px_label()
        self.layers, self.set_key = [], None
        self.view.set_image(self.original)
        self.start_calc()

    # ------------------------------------------------------------ расчёт

    def schedule_calc(self, *_):
        if self.chk_auto.isChecked():
            self.recalc_timer.start()

    def calc_params(self):
        return dict(
            levels=self.sp_levels.value(), max_paints=self.sp_paints.value(), clusters=self.sp_clusters.value(),
            lam_paint=self.sp_lam_paint.value(), lam_density=self.sp_lam_dens.value(),
            smooth_sp=6 if self.sp_sr.value() > 0 else 0, smooth_sr=max(self.sp_sr.value(), 1),
            boundary_sigma=self.sp_bsigma.value(), min_area_frac=self.sp_area.value() / 100.0,
            feather=self.sp_feather.value() / 100.0 * max(self.original.shape[:2]),
            edge_threshold=self.sp_edge.value(),
        )

    def start_calc(self):
        self.recalc_timer.stop()
        if self.original is None:
            return
        if self.thread is not None:
            self.pending = True
            return
        key = self.cb_set.currentData()
        if key != self.set_key or not self.layers:
            paints = self.paints_for_key(key)
            if not paints:
                return
            self.layers = [Layer(p, np.zeros(self.original.shape[:2], np.float32)) for p in paints]
            self.apply_pending_layer_state()
            self.set_key = key
            self.selected = 0
            self.layers_panel.set_layers(self.layers, self.selected)
        paints = [l.paint for l in self.layers]
        self.thread = CalcThread(self.original, paints_od(paints), self.calc_params(), [p.id for p in paints])
        self.thread.done.connect(self.on_calc_done)
        self.thread.failed.connect(self.on_calc_failed)
        self.thread.finished.connect(self.on_thread_finished)
        self.progress.setRange(0, 0)
        self.lbl_status.setText("Считаю слои…")
        self.thread.start()

    def on_calc_done(self, dec, ids):
        if dec.layers.shape[1:] != self.original.shape[:2]:
            return  # за время расчёта загрузили другое фото — результат устарел
        by_id = {pid: i for i, pid in enumerate(ids)}
        for layer in self.layers:
            if layer.paint.id in by_id:
                layer.t = dec.layers[by_id[layer.paint.id]]
        self.recipe_map = dec.recipe_map
        self.update_outline(render=False)
        self.lbl_status.setText("Готово")
        self.render()

    def on_calc_failed(self, message):
        self.lbl_status.setText("Ошибка расчёта")
        QMessageBox.warning(self, "Ошибка расчёта", message)

    def on_thread_finished(self):
        self.thread = None
        self.progress.setRange(0, 1)
        if self.pending:
            self.pending = False
            self.start_calc()

    # ------------------------------------------------------------ контур

    def update_outline(self, *_, render=True):
        if self.original is None:
            return
        self.outline = build_outline(
            self.recipe_map, self.original, use_regions=self.chk_regions.isChecked(),
            use_photo=self.chk_photo.isChecked(), thickness=self.sp_thick.value(),
            photo_threshold=self.sl_edge.value(),
        )
        if render:
            self.render()

    def change_outline_color(self):
        color = QColorDialog.getColor(QColor(*self.outline_color), self, "Цвет контурных линий")
        if color.isValid():
            self.outline_color = (color.red(), color.green(), color.blue())
            self._paint_outline_button()
            self.render()

    # ------------------------------------------------------------ слои

    def select_layer(self, index):
        self.selected = index
        self.layers_panel.set_layers(self.layers, index)
        if self.cb_mode.currentText() == "Выбранный слой":
            self.render()

    def reorder_layer(self, index, delta):
        j = index + delta
        if 0 <= j < len(self.layers):
            self.layers[index], self.layers[j] = self.layers[j], self.layers[index]
            self.selected = j
            self.layers_panel.set_layers(self.layers, j)
            self.render()

    def change_color(self, index):
        layer = self.layers[index]
        color = QColorDialog.getColor(QColor(*layer.paint.rgb), self, "Колер краски: " + layer.paint.name_ru)
        if color.isValid():
            layer.paint = dataclasses.replace(layer.paint, rgb=(color.red(), color.green(), color.blue()))
            self.layers_panel.set_layers(self.layers, index)
            self.render()
            self.schedule_calc()

    # ------------------------------------------------------------ превью

    def _compose(self, layers):
        if not layers:
            return np.full(self.original.shape, 255, np.uint8)
        t = np.stack([l.t * l.opacity for l in layers])
        return composite(t, np.stack([l.paint.od for l in layers]))

    def render(self, *_):
        if self.original is None:
            return
        mode = self.cb_mode.currentText()
        self.sl_split.setVisible(mode == "Сравнение")
        result = None
        if mode == "Оригинал":
            img = self.original
        elif mode == "Выбранный слой":
            img = self._compose([self.layers[self.selected]] if self.layers else [])
        else:
            result = self._compose([l for l in self.layers if l.visible])
            img = result
            if mode == "Сравнение":
                x = int(self.original.shape[1] * self.sl_split.value() / 100)
                img = result.copy()
                img[:, :x] = self.original[:, :x]
                img[:, max(x - 1, 0):x + 1] = (255, 255, 255)

        overlay = None
        if mode != "Оригинал":
            if self.chk_show_outline.isChecked() and self.outline is not None:
                overlay = self.outline
            if self.chk_marks.isChecked():
                h, w = self.original.shape[:2]
                marks = registration_marks((w, h), w / (self.sp_w.value() / MM_PER_INCH), self.sp_inset.value())
                overlay = marks if overlay is None else np.maximum(overlay, marks)
        if overlay is not None:
            a = overlay[..., None]
            img = np.rint(img * (1 - a) + np.array(self.outline_color, np.float32) * a).astype(np.uint8)
        self.view.set_image(img)

        if result is not None:
            rep = error_report(self.original, result)
            self.lbl_err.setText("ΔE среднее %.1f · медиана %.1f · 95%% %.1f" % (
                rep["dE_mean"], rep["dE_median"], rep["dE_p95"]))
        else:
            self.lbl_err.setText("")

    # ------------------------------------------------------------ экспорт

    def _link_size(self, from_width):
        if self.original is None:
            return
        h, w = self.original.shape[:2]
        for src, dst, ratio in ((self.sp_w, self.sp_h, h / w), (self.sp_h, self.sp_w, w / h)):
            if (src is self.sp_w) == from_width:
                dst.blockSignals(True)
                dst.setValue(round(src.value() * ratio, 1))
                dst.blockSignals(False)
        self._update_px_label()

    def _update_px_label(self, *_):
        w, h = mm_to_px(self.sp_w.value(), self.sp_dpi.value()), mm_to_px(self.sp_h.value(), self.sp_dpi.value())
        self.lbl_px.setText("%d × %d px" % (w, h))

    def export(self):
        visible = [l for l in self.layers if l.visible and l.t.max() > 0 and l.opacity > 0]
        if self.original is None or not self.layers:
            QMessageBox.information(self, "Экспорт", "Сначала загрузите фото и рассчитайте слои.")
            return
        base = ROOT / "output"
        base.mkdir(exist_ok=True)
        folder = QFileDialog.getExistingDirectory(self, "Папка для экспорта", str(base))
        if not folder:
            return
        dpi = self.sp_dpi.value()
        size = (mm_to_px(self.sp_w.value(), dpi), mm_to_px(self.sp_h.value(), dpi))
        out = Path(folder) / safe_filename("%s_%s" % (self.source_name, self.current_set_label()))

        items = []
        if self.outline is not None:
            items.append(("00_Outline", self.outline_color, self.outline))
        for n, layer in enumerate(visible, start=1):
            items.append(("%02d_%s" % (n, slugify(layer.paint.name_en) if layer.paint.name_en else layer.paint.id),
                          layer.paint.rgb, layer.t * layer.opacity))
        try:
            marks = registration_marks(size, dpi, self.sp_inset.value()) if self.chk_marks.isChecked() else None
            export_layer_set(items, out, size, dpi, white_background=self.chk_white.isChecked(),
                             marks=marks, mark_color=self.outline_color)
            result = cv2.resize(self._compose(visible), size, interpolation=cv2.INTER_AREA)
            Image.fromarray(result).save(out / "result.png", dpi=(dpi, dpi))
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка экспорта", str(exc))
            return
        self.lbl_status.setText("Экспортировано: %s" % out)
        QMessageBox.information(
            self, "Экспорт завершён",
            "Слоёв: %d%s\nРазмер: %d × %d px, %d dpi (%.0f × %.0f мм)\n\n%s" % (
                len(visible), " + контур" if self.outline is not None else "", size[0], size[1], dpi,
                self.sp_w.value(), self.sp_h.value(), out))
