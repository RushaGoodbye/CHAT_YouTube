"""Non-broadcast modal for selecting an embedded video's visible rectangle.

The crop is selected over a still frame, not over the live OBS surface, so
the broadcast layout and source window geometry remain completely unchanged.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QDialog, QWidget, QLabel, QDialogButtonBox, QVBoxLayout,
)

from video_fit import Crop


class CropCanvas(QWidget):
    def __init__(self, image: QImage, crop: Crop | None = None, parent=None):
        super().__init__(parent)
        self.image = image.copy()
        self.setMinimumSize(580, 345)
        self.setMouseTracking(True)
        self.begin: QPointF | None = None
        self.end: QPointF | None = None
        self.value = crop
        self.dragging = False

    def _picture_rect(self) -> QRectF:
        if self.image.isNull() or self.width() <= 0 or self.height() <= 0:
            return QRectF()
        scale = min(self.width()/self.image.width(),
                    self.height()/self.image.height())
        width = self.image.width()*scale
        height = self.image.height()*scale
        return QRectF((self.width()-width)/2, (self.height()-height)/2,
                      width, height)

    def _normalized(self, pos: QPointF) -> QPointF:
        r = self._picture_rect()
        if r.isEmpty():
            return QPointF(0, 0)
        return QPointF(max(0.0, min(1.0, (pos.x()-r.left())/r.width())),
                       max(0.0, min(1.0, (pos.y()-r.top())/r.height())))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._picture_rect().contains(event.position()):
            return
        self.begin = self._normalized(event.position())
        self.end = self.begin
        self.dragging = True
        self.update()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.end = self._normalized(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.end = self._normalized(event.position())
            self.dragging = False
            self.update()

    def selected_crop(self) -> Crop | None:
        if self.begin is None or self.end is None:
            return self.value
        left, right = sorted((self.begin.x(), self.end.x()))
        top, bottom = sorted((self.begin.y(), self.end.y()))
        if right-left < .06 or bottom-top < .06:
            return None
        return Crop(left, top, right, bottom)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#090a0c"))
        rect = self._picture_rect()
        if rect.isEmpty():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(rect, self.image)
        crop = self.selected_crop()
        if crop:
            highlight = QRectF(
                rect.left() + crop.left*rect.width(),
                rect.top() + crop.top*rect.height(),
                crop.width*rect.width(),
                crop.height*rect.height(),
            )
            painter.fillRect(highlight, QColor(65, 175, 225, 35))
            painter.setPen(QPen(QColor("#40c5ef"), 3))
            painter.drawRect(highlight)
        painter.end()


class CropSelectionDialog(QDialog):
    def __init__(self, image: QImage, existing: Crop | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Обрати основний відеокадр")
        self.resize(850, 610)
        layout = QVBoxLayout(self)
        label = QLabel(
            "Виділіть мишею прямокутник з основним відео. "
            "Усі написи та поля за його межами будуть приховані. "
            "Сам розмір вікна OBS не зміниться.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.canvas = CropCanvas(image, existing, self)
        layout.addWidget(self.canvas, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.crop: Crop | None = None

    def accept(self):
        selection = self.canvas.selected_crop()
        if selection is None:
            self.canvas.setToolTip("Виділіть ділянку, що займає щонайменше 6% кадру.")
            return
        self.crop = selection
        super().accept()
