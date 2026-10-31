"""Превью с масштабированием колесом, перетаскиванием и подгонкой по двойному клику."""
import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class ImageView(QGraphicsView):
    clicked = pyqtSignal(float, float)  # координаты клика в пикселях изображения (без перетаскивания)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press = None
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._item)
        self._size = None
        self._fitted = True
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self.setBackgroundBrush(QColor(45, 45, 48))
        self.setFrameShape(QGraphicsView.NoFrame)

    def set_image(self, rgb):
        """rgb: (H, W, 3) uint8."""
        rgb = np.ascontiguousarray(rgb)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._item.setPixmap(QPixmap.fromImage(qimg))
        if self._size != (w, h):
            self._size = (w, h)
            self._scene.setSceneRect(0, 0, w, h)
            self.fit()

    def fit(self):
        if self._size:
            self.fitInView(self._item, Qt.KeepAspectRatio)
            self._fitted = True

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        self._fitted = False

    def mouseDoubleClickEvent(self, event):
        self.fit()

    def mousePressEvent(self, event):
        self._press = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._press is not None and (event.pos() - self._press).manhattanLength() < 5 and self._size:
            p = self.mapToScene(event.pos())
            if 0 <= p.x() < self._size[0] and 0 <= p.y() < self._size[1]:
                self.clicked.emit(p.x(), p.y())
        self._press = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fitted:
            self.fit()
