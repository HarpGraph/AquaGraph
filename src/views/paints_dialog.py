"""Редактор библиотеки красок и сборка своих наборов."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (QColorDialog, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from core.library import MAX_SET, MIN_SET
from views.calibration_dialog import CalibrationDialog


def swatch_icon(rgb):
    pix = QPixmap(22, 22)
    pix.fill(QColor(*rgb))
    return QIcon(pix)


class PaintsDialog(QDialog):
    """Слева — все краски (галочка = входит в собираемый набор), справа — свойства краски."""

    def __init__(self, library, current_set=None, parent=None):
        super().__init__(parent)
        self.library = library
        self.saved_set_name = None
        self.checked = set()
        self._loading = False
        self.setWindowTitle("Краски и наборы")
        self.resize(760, 560)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemChanged.connect(self._on_check)

        btn_add = QPushButton("Добавить краску")
        btn_dup = QPushButton("Дублировать")
        btn_del = QPushButton("Удалить краску")
        btn_add.clicked.connect(self.add_paint)
        btn_dup.clicked.connect(self.duplicate_paint)
        btn_del.clicked.connect(self.delete_paint)
        buttons = QHBoxLayout()
        for b in (btn_add, btn_dup, btn_del):
            buttons.addWidget(b)
        left = QVBoxLayout()
        left.addWidget(QLabel("Библиотека красок (галочка — краска в наборе)"))
        left.addWidget(self.list, 1)
        left.addLayout(buttons)

        self.props = QGroupBox("Краска")
        form = QFormLayout(self.props)
        self.ed_ru, self.ed_en, self.ed_hex = QLineEdit(), QLineEdit(), QLineEdit()
        self.btn_color = QPushButton()
        self.btn_color.setFixedHeight(28)
        self.btn_calib = QPushButton("Калибровка по пробнику…")
        self.btn_calib.setToolTip("Уточнить колер по фото мазков краски на бумаге")
        self.btn_calib.clicked.connect(self._calibrate)
        self.lbl_note = QLabel()
        self.lbl_note.setWordWrap(True)
        self.ed_ru.editingFinished.connect(self._apply_names)
        self.ed_en.editingFinished.connect(self._apply_names)
        self.ed_hex.editingFinished.connect(self._apply_hex)
        self.btn_color.clicked.connect(self._pick_color)
        form.addRow("Название (рус):", self.ed_ru)
        form.addRow("Название (eng):", self.ed_en)
        form.addRow("Колер:", self.btn_color)
        form.addRow("HEX:", self.ed_hex)
        form.addRow(self.btn_calib)
        form.addRow(self.lbl_note)

        self.set_box = QGroupBox("Набор")
        sf = QFormLayout(self.set_box)
        self.cb_load = QComboBox()
        self.cb_load.addItem("— взять состав из набора —", None)
        for s in library.sets():
            self.cb_load.addItem(s.name, s.name)
        self.cb_load.activated.connect(self._load_set)
        self.ed_set = QLineEdit()
        self.ed_set.setPlaceholderText("Название нового набора")
        self.lbl_count = QLabel()
        btn_save = QPushButton("Сохранить набор")
        btn_save.clicked.connect(self.save_set)
        sf.addRow(self.cb_load)
        sf.addRow("Название:", self.ed_set)
        sf.addRow(self.lbl_count)
        sf.addRow(btn_save)

        right = QVBoxLayout()
        right.addWidget(self.props)
        right.addWidget(self.set_box)
        right.addStretch(1)
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        right.addWidget(btn_close)

        root = QHBoxLayout(self)
        root.addLayout(left, 3)
        root.addLayout(right, 2)

        start = library.get_set(current_set) if current_set else None
        self.checked = {p.id for p in start.paints} if start else set()
        self.fill_list()
        self._update_count()

    # ---------------------------------------------------------- список

    def fill_list(self, select_id=None):
        self._loading = True
        self.list.clear()
        for p in self.library.paints:
            user = self.library.is_user_paint(p.id)
            item = QListWidgetItem(swatch_icon(p.rgb), p.name_ru + ("" if user else "  · заводская"))
            item.setData(Qt.UserRole, p.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if p.id in self.checked else Qt.Unchecked)
            self.list.addItem(item)
            if p.id == select_id:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._loading = False
        self._on_current(self.list.currentItem(), None)

    def _current_paint(self):
        item = self.list.currentItem()
        return self.library.get_paint(item.data(Qt.UserRole)) if item else None

    def _on_current(self, item, _prev):
        if self._loading:
            return
        p = self._current_paint()
        editable = p is not None and self.library.is_user_paint(p.id)
        for w in (self.ed_ru, self.ed_en, self.ed_hex, self.btn_color, self.btn_calib):
            w.setEnabled(editable)
        if p is None:
            return
        self.ed_ru.setText(p.name_ru)
        self.ed_en.setText(p.name_en)
        self.ed_hex.setText(QColor(*p.rgb).name().upper())
        self.btn_color.setStyleSheet("background:%s; border:1px solid #222;" % QColor(*p.rgb).name())
        self.lbl_note.setText("" if editable else "Заводскую краску менять нельзя — нажмите «Дублировать» и правьте копию.")

    def _on_check(self, item):
        if self._loading:
            return
        pid = item.data(Qt.UserRole)
        (self.checked.add if item.checkState() == Qt.Checked else self.checked.discard)(pid)
        self._update_count()

    def _update_count(self):
        n = len(self.checked)
        ok = MIN_SET <= n <= MAX_SET
        self.lbl_count.setText("Выбрано красок: %d (нужно от %d до %d)" % (n, MIN_SET, MAX_SET))
        self.lbl_count.setStyleSheet("" if ok else "color:#e07050;")

    # ---------------------------------------------------------- правка красок

    def add_paint(self):
        p = self.library.add_paint("Новая краска", "New Paint", (120, 120, 120))
        self.fill_list(p.id)

    def duplicate_paint(self):
        p = self._current_paint()
        if p:
            new = self.library.add_paint(p.name_ru + " (копия)", p.name_en + " copy", p.rgb)
            self.fill_list(new.id)

    def delete_paint(self):
        p = self._current_paint()
        if not p or not self.library.is_user_paint(p.id):
            QMessageBox.information(self, "Удаление", "Удалять можно только свои краски.")
            return
        if QMessageBox.question(self, "Удалить краску", "Удалить «%s» из библиотеки?\n"
                                "Уже сохранённые наборы останутся как есть." % p.name_ru) != QMessageBox.Yes:
            return
        self.library.delete_paint(p.id)
        self.checked.discard(p.id)
        self.fill_list()
        self._update_count()

    def _update_current(self, **fields):
        p = self._current_paint()
        if p and self.library.is_user_paint(p.id):
            self.library.update_paint(p.id, **fields)
            self.fill_list(p.id)

    def _apply_names(self):
        ru, en = self.ed_ru.text().strip(), self.ed_en.text().strip()
        p = self._current_paint()
        if p and (ru or en) and (ru != p.name_ru or en != p.name_en):
            self._update_current(name_ru=ru or en, name_en=en or ru)

    def _apply_hex(self):
        color = QColor(self.ed_hex.text().strip())
        p = self._current_paint()
        if color.isValid() and p and (color.red(), color.green(), color.blue()) != tuple(p.rgb):
            self._update_current(rgb=(color.red(), color.green(), color.blue()))
        else:
            self._on_current(self.list.currentItem(), None)

    def _pick_color(self):
        p = self._current_paint()
        if p:
            color = QColorDialog.getColor(QColor(*p.rgb), self, "Колер краски")
            if color.isValid():
                self._update_current(rgb=(color.red(), color.green(), color.blue()))

    def _calibrate(self):
        p = self._current_paint()
        if p is None or not self.library.is_user_paint(p.id):
            return
        dialog = CalibrationDialog(p.name_ru, self)
        if dialog.exec_() and dialog.result_rgb is not None:
            self._update_current(rgb=dialog.result_rgb)

    # ---------------------------------------------------------- наборы

    def _load_set(self):
        name = self.cb_load.currentData()
        s = self.library.get_set(name) if name else None
        if not s:
            return
        for p in s.paints:  # недостающие краски (например из чужого пресета) добавляем в библиотеку
            if self.library.get_paint(p.id) is None:
                self.library.user_paints.append(p)
        self.library.save()
        self.checked = {p.id for p in s.paints}
        self.ed_set.setText("" if s.builtin else s.name)
        self.fill_list()
        self._update_count()

    def save_set(self):
        name = self.ed_set.text().strip()
        paints = sorted((p for p in self.library.paints if p.id in self.checked), key=lambda p: -p.lightness)
        if not name:
            QMessageBox.information(self, "Набор", "Введите название набора.")
            return
        if self.library.is_builtin_set(name):
            QMessageBox.warning(self, "Набор", "Это название занято заводским набором.")
            return
        if not MIN_SET <= len(paints) <= MAX_SET:
            QMessageBox.warning(self, "Набор", "В наборе должно быть от %d до %d красок." % (MIN_SET, MAX_SET))
            return
        if name in self.library.user_sets and QMessageBox.question(
                self, "Набор", "Набор «%s» уже есть. Заменить?" % name) != QMessageBox.Yes:
            return
        self.library.save_set(name, paints)
        self.saved_set_name = name
        if self.cb_load.findData(name) < 0:
            self.cb_load.addItem(name, name)
        QMessageBox.information(self, "Набор", "Набор «%s» сохранён (%d красок)." % (name, len(paints)))
