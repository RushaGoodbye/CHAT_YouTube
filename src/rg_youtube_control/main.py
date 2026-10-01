import sys
from PySide6.QtWidgets import QApplication
from .config import APP_NAME
from .ui import MainWindow

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())