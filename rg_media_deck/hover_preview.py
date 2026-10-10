"""Centered media hover preview, isolated from the OBS playback surface."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

POPUP_WIDTH = 306
IMAGE_WIDTH = 278
IMAGE_HEIGHT = 186


def centered_popup_position(anchor: QPoint, bounds: QRect, width: int,
                            height: int, gap: int = 18) -> QPoint:
    """Center horizontally at the pointer and stay entirely on its screen."""
    if width <= 0 or height <= 0 or bounds.width() <= 0 or bounds.height() <= 0:
        raise ValueError("Invalid preview or screen size")
    x = max(bounds.left(), min(anchor.x() - width // 2,
                               bounds.right() - width + 1))
    if anchor.y() + gap + height <= bounds.bottom() + 1:
        y = anchor.y() + gap
    elif anchor.y() - gap - height >= bounds.top():
        y = anchor.y() - gap - height
    else:
        y = max(bounds.top(), min(anchor.y() + gap,
                                  bounds.bottom() - height + 1))
    return QPoint(x, y)


class MediaHoverPopup(QWidget):
    """Fixed-width dark popup; thumbnail and caption are horizontally centered."""
    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.ToolTip |
                         Qt.WindowType.FramelessWindowHint)
        self.setObjectName("MediaHoverPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(POPUP_WIDTH)
        self.setStyleSheet(
            "QWidget#MediaHoverPopup {background:#191b20; "
            "border:1px solid #484b54; border-radius:8px;}"
            "QLabel {background:transparent; color:#eef0f3; border:none;}"
            "QLabel#HoverImage {background:#090a0c; border-radius:4px;}"
            "QLabel#HoverDetails {color:#aeb3be; font-size:11px;}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        self.image = QLabel()
        self.image.setObjectName("HoverImage")
        self.image.setFixedSize(IMAGE_WIDTH, IMAGE_HEIGHT)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.caption = QLabel()
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter |
                                  Qt.AlignmentFlag.AlignVCenter)
        self.caption.setFixedHeight(20)
        layout.addWidget(self.caption)

        self.details = QLabel()
        self.details.setObjectName("HoverDetails")
        self.details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details.setFixedHeight(16)
        layout.addWidget(self.details)
        self.adjustSize()

    def show_media(self, image_path: str, title: str, details: str,
                   anchor: QPoint | None = None) -> bool:
        image = QPixmap(image_path)
        if image.isNull():
            self.hide()
            return False
        self.image.setPixmap(image.scaled(
            self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self.caption.setText(self.caption.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideMiddle, IMAGE_WIDTH))
        self.details.setText(details)
        self.adjustSize()
        pointer = anchor if anchor is not None else QCursor.pos()
        screen = QGuiApplication.screenAt(pointer) or QGuiApplication.primaryScreen()
        if screen is None:
            self.hide()
            return False
        self.move(centered_popup_position(pointer, screen.availableGeometry(),
                                          self.width(), self.height()))
        self.show()
        return True
