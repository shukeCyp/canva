import sys
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme
from app.ui.main_window import MainWindow
from app.tools.open_leonardo_account import open_account


def main():
    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--open-account":
        open_account(sys.argv[2])
        raise SystemExit(0)
    main()
