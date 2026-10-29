import json
import os
import sys

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QLockFile, QStandardPaths, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from .config import APP_NAME
from .comment_action_ui import install_comment_action_ui
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
    install_comment_action_ui(window)
    window.show()

    # Explicit CI-only probe. A marker proves that the frozen executable
    # entered Qt's event loop and responded after its initial table loads.
    smoke_path = os.environ.get("RG_YT_QA_SMOKE_FILE", "").strip()
    if smoke_path:
        def finish_smoke() -> None:
            try:
                marker = Path(smoke_path)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    json.dumps({
                        "visible": window.isVisible(),
                        "tab_count": window.tabs.count(),
                        "build_label": window.version_label.text(),
                        "utc": datetime.now(timezone.utc).isoformat(),
                    }),
                    encoding="utf-8",
                )
            finally:
                app.quit()

        QTimer.singleShot(5000, finish_smoke)

    # A separate probe checks responsiveness after the 12s archive-recovery
    # timer has fired. The 5s probe above deliberately exits early; use
    # this longer one instead when testing delayed startup hangs.
    stability_path = os.environ.get("RG_YT_QA_STABILITY_FILE", "").strip()
    if stability_path:
        def finish_stability_probe() -> None:
            try:
                marker = Path(stability_path)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(
                    json.dumps({
                        "visible": window.isVisible(),
                        "tab_count": window.tabs.count(),
                        "build_label": window.version_label.text(),
                        "utc": datetime.now(timezone.utc).isoformat(),
                    }),
                    encoding="utf-8",
                )
            finally:
                app.quit()

        QTimer.singleShot(20000, finish_stability_probe)

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