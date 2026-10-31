"""Диалог сохранения пресета настроек."""
from PyQt5.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit


class PresetSaveDialog(QDialog):
    def __init__(self, name="", has_image=False, ask_name=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сохранить пресет настроек")
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        self.ed_name = QLineEdit(name)
        self.chk_image = QCheckBox("Включить путь к фото")
        self.chk_image.setEnabled(has_image)
        self.chk_image.setToolTip("Пресет будет сам открывать это фото. Без галочки настройки применяются к текущему.")
        if ask_name:
            form.addRow("Название:", self.ed_name)
        form.addRow(self.chk_image)
        if not has_image:
            form.addRow(QLabel("Фото не загружено — путь сохранить нечем."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def name(self):
        return self.ed_name.text().strip()

    @property
    def include_image(self):
        return self.chk_image.isEnabled() and self.chk_image.isChecked()
