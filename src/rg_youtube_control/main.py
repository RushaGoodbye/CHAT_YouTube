import sys

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QLockFile, QStandardPaths, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from .config import APP_NAME
from .service import archive_priority_enabled
from .ui import MainWindow

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    lock_path = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    ) / "rg_youtube_control_gui.lock"
    single_instance_lock = QLockFile(str(lock_path))
    if not single_instance_lock.tryLock(100):
        return 0
    app._rg_single_instance_lock = single_instance_lock

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