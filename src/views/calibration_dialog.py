"""Калибровка краски по фото пробника."""
import cv2
import numpy as np
from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox,
                             QPushButton, QRadioButton, QVBoxLayout)

from core.calibrate import estimate_paint_rgb, sample_patch
from views.image_view import ImageView

MAX_SIDE = 2000
HELP = ("Нанесите краску полосами разной густоты рядом с чистой бумагой, сфотографируйте при ровном свете. "
        "Кликните по чистой бумаге, затем по мазкам, указывая густоту каждого мазка (самый густой — 100 %).")


class CalibrationDialog(QDialog):
    def __init__(self, paint_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Калибровка краски: " + paint_name)
        self.resize(980, 700)
        self.result_rgb = None
        self.image = None
        self.paper = None          # (x, y, rgb)
        self.samples = []          # (x, y, rgb, density)

        btn_open = QPushButton("Открыть фото пробника…")
        btn_open.clicked.connect(self.open_image)
        self.rb_paper = QRadioButton("Бумага")
        self.rb_paint = QRadioButton("Мазок краски, густота:")
        self.rb_paint.setChecked(True)
        self.sp_density = QDoubleSpinBox()
        self.sp_density.setRange(5, 100)
        self.sp_density.setValue(100)
        self.sp_density.setSuffix(" %")
        top = QHBoxLayout()
        for w in (btn_open, self.rb_paper, self.rb_paint, self.sp_density):
            top.addWidget(w)
        top.addStretch(1)

        self.view = ImageView()
        self.view.clicked.connect(self.on_click)
        self.list = QListWidget()
        self.list.setMaximumWidth(260)
        btn_del = QPushButton("Убрать выбранную точку")
        btn_del.clicked.connect(self.remove_selected)
        self.lbl_result = QLabel("Результат появится после первого мазка")
        self.lbl_result.setWordWrap(True)
        self.swatch = QLabel()
        self.swatch.setFixedHeight(36)
        side = QVBoxLayout()
        side.addWidget(QLabel("Точки"))
        side.addWidget(self.list, 1)
        side.addWidget(btn_del)
        side.addWidget(self.swatch)
        side.addWidget(self.lbl_result)
        middle = QHBoxLayout()
        middle.addWidget(self.view, 1)
        middle.addLayout(side)

        self.btn_ok = QPushButton("Применить к краске")
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.btn_ok)
        bottom.addWidget(btn_cancel)

        hint = QLabel(HELP)
        hint.setWordWrap(True)
        root = QVBoxLayout(self)
        root.addWidget(hint)
        root.addLayout(top)
        root.addLayout(middle, 1)
        root.addLayout(bottom)

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Фото пробника", "", "Изображения (*.png *.jpg *.jpeg *.bmp *.webp);;Все файлы (*)")
        if path:
            self.load_image(path)

    def load_image(self, path):
        img = Image.open(path).convert("RGB")
        scale = MAX_SIDE / max(img.size)
        if scale < 1:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        self.image = np.asarray(img)
        self.paper, self.samples = None, []
        self.refresh()

    def on_click(self, x, y):
        if self.image is None:
            return
        radius = max(3, round(min(self.image.shape[:2]) * 0.008))
        rgb = sample_patch(self.image, x, y, radius)
        if self.rb_paper.isChecked():
            self.paper = (x, y, rgb)
        else:
            self.samples.append((x, y, rgb, self.sp_density.value() / 100.0))
        self.refresh()

    def remove_selected(self):
        row = self.list.currentRow()
        if row < 0:
            return
        if self.paper is not None and row == 0:
            self.paper = None
        else:
            del self.samples[row - (1 if self.paper is not None else 0)]
        self.refresh()

    def refresh(self):
        self.list.clear()
        if self.paper is not None:
            self.list.addItem("Бумага — %s" % QColor(*self.paper[2]).name().upper())
        for _, _, rgb, d in self.samples:
            self.list.addItem("Мазок %d %% — %s" % (round(d * 100), QColor(*rgb).name().upper()))

        if self.image is not None:
            canvas = self.image.copy()
            r = max(6, round(min(canvas.shape[:2]) * 0.012))
            marks = [(self.paper[0], self.paper[1], (255, 255, 255))] if self.paper else []
            marks += [(x, y, (255, 60, 60)) for x, y, _, _ in self.samples]
            for x, y, color in marks:
                cv2.circle(canvas, (int(x), int(y)), r, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.circle(canvas, (int(x), int(y)), r, color, 1, cv2.LINE_AA)
            self.view.set_image(canvas)

        self.result_rgb = None
        if self.samples:
            self.result_rgb = estimate_paint_rgb(
                [s[2] for s in self.samples], [s[3] for s in self.samples], self.paper[2] if self.paper else None)
            self.swatch.setStyleSheet("background:%s; border:1px solid #222;" % QColor(*self.result_rgb).name())
            note = "" if self.paper else "\nБез чистой бумаги баланс белого не выровнен."
            self.lbl_result.setText("Колер на полной густоте: RGB %d, %d, %d (%s)%s" % (
                *self.result_rgb, QColor(*self.result_rgb).name().upper(), note))
        else:
            self.swatch.setStyleSheet("")
            self.lbl_result.setText("Результат появится после первого мазка")
        self.btn_ok.setEnabled(self.result_rgb is not None)
