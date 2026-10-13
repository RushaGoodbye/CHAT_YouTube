"""Privacy-safe OBS Window Capture output, independent of app panel ordering.

Mirrors already-decoded QImages: no second media decoder/audio output.
Only media pixels, never Telegram chats, ChatGPT, settings or passwords.
The dedicated top-level output is optional, opened with an explicit command.
Stable window title and dimensions regardless of left/right main player pane.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget
from video_fit import fill_frame_crop, fitted_frame_rect


class OBSSafeVideoWindow(QWidget):
    WINDOW_TITLE = "RG MEDIA DECK - SAFE VIDEO"

    def __init__(self, source, parent=None):
        super().__init__(None)
        self.source = source
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setMinimumSize(320, 180)
        self.resize(960, 540)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background:black;")
        self._timer = QTimer(self)
        self._timer.setInterval(34)
        self._timer.timeout.connect(self.update)
        self._frames_painted = 0

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        current = self.source.current
        if current is None:
            return
        if current.kind == "photo":
            image = self.source.photo.pixmap_source
            if image is None or image.isNull():
                return
            size = image.size()
            area = size.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            dest = QRectF((self.width()-area.width())/2,
                          (self.height()-area.height())/2,
                          area.width(), area.height())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawPixmap(dest.toRect(), image)
            self._frames_painted += 1
            return
        viewport = self.source.video_view
        image = viewport._image
        if image is None or image.isNull():
            return
        crop = (viewport.crop if viewport.forced_portrait
                or viewport.fit_mode in ("auto", "manual")
                else fill_frame_crop(self.width(), self.height(),
                                     image.width(), image.height())
                if viewport.fit_mode == "fill" else None)
        destination, original = fitted_frame_rect(
            self.width(), self.height(), image.width(), image.height(), crop)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(*destination), image, QRectF(*original))
        self._frames_painted += 1

    def shutdown(self):
        self._timer.stop()
        self.close()
