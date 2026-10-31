"""Панель слоёв: глаз, цвет, имя, плотность, порядок."""
from dataclasses import dataclass

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout,
                             QWidget)

from core.palettes import Paint


@dataclass
class Layer:
    paint: Paint
    t: np.ndarray            # (H, W) густота [0..1]
    visible: bool = True
    opacity: float = 1.0     # множитель густоты слоя


class LayerRow(QFrame):
    changed = pyqtSignal()
    selected = pyqtSignal(int)
    move = pyqtSignal(int, int)
    pick_color = pyqtSignal(int)

    def __init__(self, index, layer, is_selected, parent=None):
        super().__init__(parent)
        self.index, self.layer = index, layer
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("LayerRow { border: 1px solid %s; }" % ("#e0a030" if is_selected else "#555"))

        self.eye = QCheckBox()
        self.eye.setChecked(layer.visible)
        self.eye.setToolTip("Показать / скрыть (скрытые слои не экспортируются)")
        self.eye.toggled.connect(self._on_visible)

        self.swatch = QPushButton()
        self.swatch.setFixedSize(26, 26)
        self.swatch.setStyleSheet("background:%s; border:1px solid #222;" % QColor(*layer.paint.rgb).name())
        self.swatch.setToolTip("Сменить колер")
        self.swatch.clicked.connect(lambda: self.pick_color.emit(self.index))

        name = QLabel("%d. %s" % (index + 1, layer.paint.name_ru))
        name.setToolTip(layer.paint.name_en)
        name.setMinimumWidth(110)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(layer.opacity * 100)))
        self.slider.setToolTip("Плотность слоя")
        self.slider.valueChanged.connect(self._on_opacity)

        up, down = QPushButton("▲"), QPushButton("▼")
        for b, d in ((up, -1), (down, 1)):
            b.setFixedSize(24, 24)
            b.clicked.connect(lambda _=False, d=d: self.move.emit(self.index, d))

        top = QHBoxLayout()
        for w in (self.eye, self.swatch, name):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(up)
        top.addWidget(down)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        lay.addLayout(top)
        lay.addWidget(self.slider)

    def _on_visible(self, checked):
        self.layer.visible = checked
        self.changed.emit()

    def _on_opacity(self, value):
        self.layer.opacity = value / 100.0
        self.changed.emit()

    def mousePressEvent(self, event):
        self.selected.emit(self.index)
        super().mousePressEvent(event)


class LayersPanel(QWidget):
    changed = pyqtSignal()
    selected = pyqtSignal(int)
    reorder = pyqtSignal(int, int)
    pick_color = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._box = QVBoxLayout()
        self._box.setAlignment(Qt.AlignTop)
        holder = QWidget()
        holder.setLayout(self._box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(QLabel("Слои (светлые → тёмные)"))
        outer.addWidget(scroll)

    def set_layers(self, layers, selected):
        while self._box.count():
            item = self._box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, layer in enumerate(layers):
            row = LayerRow(i, layer, i == selected)
            row.changed.connect(self.changed)
            row.selected.connect(self.selected)
            row.move.connect(self.reorder)
            row.pick_color.connect(self.pick_color)
            self._box.addWidget(row)
