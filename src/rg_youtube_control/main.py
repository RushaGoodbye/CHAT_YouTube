import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .config import APP_NAME
from .ui import MainWindow

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    locale = QLocale(QLocale.Language.Ukrainian, QLocale.Country.Ukraine)
    QLocale.setDefault(locale)
    qt_translator = QTranslator(app)
    translations_path = QLibraryInfo.path(
        QLibraryInfo.LibraryPath.TranslationsPath
    )
    if qt_translator.load("qtbase_uk", translations_path):
        app.installTranslator(qt_translator)

    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())