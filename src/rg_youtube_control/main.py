import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from .config import APP_NAME
from .service import archive_priority_enabled
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

    campaign_timer = QTimer(window)
    campaign_timer.setInterval(60 * 1000)

    def poll_campaign() -> None:
        if archive_priority_enabled(window.conn):
            window._run_archive_campaign_autorun()

    campaign_timer.timeout.connect(poll_campaign)
    campaign_timer.start()
    window._campaign_quota_timer = campaign_timer
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())