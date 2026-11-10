"""Isolated desktop entrypoint for safe SEO v2 operator preview.

No YouTube client, no legacy scheduler, no publisher and no database writes.
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from rg_youtube_control.seo_v2_ui import SEOv2PreviewTab


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("RG SEO v2 Preview")
    window = QMainWindow()
    window.setWindowTitle("РАША ГУДБАЙ | SEO v2 · тестовий перегляд")
    window.resize(1120, 760)
    window.setMinimumSize(880, 600)
    window.setCentralWidget(SEOv2PreviewTab(window))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
