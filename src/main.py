"""AquaGraph: запуск приложения."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt5.QtGui import QColor, QPalette  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from views.main_window import MainWindow  # noqa: E402


def apply_dark_theme(app):
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(53, 53, 56))
    p.setColor(QPalette.WindowText, QColor(230, 230, 230))
    p.setColor(QPalette.Base, QColor(35, 35, 38))
    p.setColor(QPalette.AlternateBase, QColor(53, 53, 56))
    p.setColor(QPalette.Text, QColor(230, 230, 230))
    p.setColor(QPalette.Button, QColor(70, 70, 74))
    p.setColor(QPalette.ButtonText, QColor(230, 230, 230))
    p.setColor(QPalette.ToolTipBase, QColor(60, 60, 64))
    p.setColor(QPalette.ToolTipText, QColor(230, 230, 230))
    p.setColor(QPalette.Highlight, QColor(224, 160, 48))
    p.setColor(QPalette.HighlightedText, QColor(20, 20, 20))
    app.setPalette(p)


def main():
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
