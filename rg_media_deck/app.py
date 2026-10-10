"""RG Media Deck - local photo/video playout for OBS Studio."""
from __future__ import annotations

import logging
import os
import sys
import subprocess
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QObject, Qt, QThread, QTimer, QUrl, Signal, QSize
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImageReader, QKeySequence, QPixmap, QShortcut, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSlider, QMenu,
    QSplitter, QStackedWidget, QTableView, QVBoxLayout, QWidget,
    QHeaderView, QAbstractItemView, QSizePolicy, QStyle,
)

import updater
from send2trash import send2trash
from video_fit import detect_letterbox, stable_crop, fitted_frame_rect

from library import MediaItem, SPEED_PRESETS, display_media_name, filter_media, load_settings, normalize_path, save_settings, scan_media, settings_path

VERSION = '0.1.8'

STYLE = """
QWidget { background:#090a0c; color:#f0f1f3; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#090a0c; }
QFrame#Panel { background:#111216; border:1px solid #262930; border-radius:9px; }
QLineEdit { background:#17191e; border:1px solid #33363e; border-radius:6px; padding:7px 10px; font-size:14px; selection-background-color:#9b2739; }
QLineEdit:focus { border:1px solid #b5384a; }
QPushButton { border:1px solid #363941; border-radius:6px; background:#1c1e24; padding:5px 9px; color:#f2f3f5; font-size:12px; font-weight:600; }
QPushButton:hover { background:#30333b; border-color:#5a5f69; }
QPushButton:pressed { background:#3e414a; }
QPushButton:disabled { background:#17191d; color:#777c85; border-color:#292d33; }
QPushButton#PlayButton { background:#b72b43; border:1px solid #ca3b52; color:white; font-size:16px; font-weight:700; padding:0; }
QPushButton#PlayButton:hover { background:#cd3a53; }
QPushButton#PauseButton, QPushButton#StopButton { background:#24262c; border:1px solid #41444d; font-size:15px; font-weight:700; padding:0; }
QPushButton#MuteButton { background:#24262c; border:1px solid #41444d; font-size:12px; font-weight:650; padding:0 5px; }
QPushButton#MuteButton:checked { background:#45242b; color:#ffb8c2; border-color:#aa4253; }
QPushButton#SettingsGear { background:#24262c; color:#e7e9ec; font-size:21px; padding:0; border-color:#33363e; }
QPushButton#SettingsGear:hover { background:#363942; }
QPushButton#SpeedStep { font-size:16px; font-weight:700; padding:0; }
QTableView { border:0; background:#111216; alternate-background-color:#191b20; selection-background-color:#5a2732; selection-color:white; gridline-color:#282a30; font-size:13px; }
QHeaderView::section { background:#1d1f25; border:0; border-bottom:1px solid #30333a; padding:7px; color:#cbd0d8; font-weight:650; }
QComboBox { border:1px solid #41444d; background:#202228; padding:5px 8px; border-radius:6px; min-width:65px; font-size:12px; }
QComboBox QAbstractItemView { background:#202228; color:#f3f3f5; selection-background-color:#723342; }
QSlider::groove:horizontal { background:#393b43; height:5px; border-radius:2px; }
QSlider::sub-page:horizontal { background:#c33950; border-radius:2px; }
QSlider::handle:horizontal { background:#eff1f4; width:14px; margin:-5px 0; border-radius:7px; }
QLabel#Status { color:#c0c4cb; font-size:11px; }
QLabel#SectionTitle { color:#f2f2f4; font-size:14px; font-weight:700; }
QLabel#SelectedFilename { color:#adb2bc; font-size:12px; }
QCheckBox { spacing:7px; }
QSplitter::handle { background:#090a0c; }
"""


def make_button(label: str, callback, name: str = '') -> QPushButton:
    button = QPushButton(label)
    if name:
        button.setObjectName(name)
    button.clicked.connect(callback)
    return button


def human_size(size: int) -> str:
    if size < 1024:
        return f'{size} Б'
    if size < 1024**2:
        return f'{size / 1024:.0f} КБ'
    if size < 1024**3:
        return f'{size / (1024**2):.1f} МБ'
    return f'{size / (1024**3):.1f} ГБ'


def timestamp(ms: int) -> str:
    seconds = max(0, int(ms) // 1000)
    hours, remain = divmod(seconds, 3600)
    minutes, second = divmod(remain, 60)
    return f'{hours:02d}:{minutes:02d}:{second:02d}' if hours else f'{minutes:02d}:{second:02d}'


class ElidedLabel(QLabel):
    """A single-line label that preserves the full text in its tooltip."""
    def __init__(self, initial: str = ''):
        super().__init__('')
        self.full_text = ''
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(95)
        self.setText(initial)

    def setText(self, text: str):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(
            self.full_text, Qt.TextElideMode.ElideMiddle, max(30, self.width() - 8)
        ))


class AspectImage(QLabel):
    """Image widget that rescales only the cached original on resize."""
    def __init__(self, placeholder: str = ''):
        super().__init__(placeholder)
        self.pixmap_source: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background:#05070b; color:#7d8c9a; border-radius:4px;')
        self.setMinimumSize(160, 90)

    def set_file(self, path: str) -> bool:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        dims = reader.size()
        if dims.isValid() and max(dims.width(), dims.height()) > 4096:
            dims.scale(4096, 4096, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(dims)
        pic = reader.read()
        if pic.isNull():
            self.pixmap_source = None
            self.setPixmap(QPixmap())
            self.setText('Не вдалося відкрити зображення')
            return False
        self.pixmap_source = QPixmap.fromImage(pic)
        self._rescale()
        return True

    def clear_image(self, message: str = ''):
        self.pixmap_source = None
        self.setPixmap(QPixmap())
        self.setText(message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self.pixmap_source is not None and not self.pixmap_source.isNull():
            self.setPixmap(self.pixmap_source.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))


class FitVideoViewport(QWidget):
    """Fixed OBS capture area. Crop only image pixels, NEVER resize the widget.

    QVideoSink supplies video frames and QPainter draws them inside this
    widget's existing rectangle. Thus automatic matte removal cannot grow any
    Qt child window, QSplitter pane or OBS capture region.
    """
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet('background:#000;')
        self.source_size = (0, 0)
        self.crop = None
        self.auto_crop = True
        self.forced_portrait = False
        self._samples = []
        self._frame_count = 0
        self._image = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def reset_crop(self):
        self.crop = None
        self._samples.clear()
        self._frame_count = 0
        self.source_size = (0, 0)
        self._image = None
        self.update()

    def set_auto_crop(self, enabled):
        self.auto_crop = bool(enabled)
        self.forced_portrait = False
        self.reset_crop()

    def set_forced_portrait(self, enabled: bool):
        self.forced_portrait = bool(enabled)
        self.crop = None
        self._samples.clear()
        self._force_portrait_if_possible()
        self.update()

    def _force_portrait_if_possible(self):
        if not self.forced_portrait:
            return
        sw, sh = self.source_size
        if sw > sh > 0:
            active_width = sh * 9 / 16
            x = (sw - active_width) / (2 * sw)
            from video_fit import Crop
            self.crop = Crop(x, 0, 1 - x, 1)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._image is None or self._image.isNull():
            return
        crop = self.crop if (self.auto_crop or self.forced_portrait) else None
        target, source = fitted_frame_rect(self.width(), self.height(),
                                           self._image.width(), self._image.height(), crop)
        from PySide6.QtCore import QRectF
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(*target), self._image, QRectF(*source))

    def observe_frame(self, frame):
        if not frame.isValid():
            return
        # Conversion is needed for pixel-space cropping; no separate decoder,
        # and no resize of a GPU-backed QVideoWidget that could escape OBS.
        picture = frame.toImage()
        if picture.isNull():
            return
        self._image = picture
        self.source_size = (picture.width(), picture.height())
        self.update()
        if self.forced_portrait:
            self._force_portrait_if_possible()
            return
        if not self.auto_crop or self.crop is not None:
            return
        self._frame_count += 1
        if self._frame_count not in (6, 14, 23, 35, 48, 64):
            return
        small = picture.scaled(192, 108, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.FastTransformation)
        mask = []
        for y in range(small.height()):
            row = []
            for x in range(small.width()):
                c = small.pixelColor(x, y)
                row.append(max(c.red(), c.green(), c.blue()) > 34)
            mask.append(row)
        self._samples.append(detect_letterbox(mask))
        self._samples = self._samples[-3:]
        detected = stable_crop(self._samples)
        if detected is not None:
            self.crop = detected
            self.update()


class ScanThread(QThread):
    scanned = Signal(object)
    counted = Signal(int)
    def __init__(self, roots: list[str]):
        super().__init__()
        self.roots = roots[:]

    def run(self):
        items = scan_media(self.roots, self.isInterruptionRequested, self.counted.emit)
        if not self.isInterruptionRequested():
            self.scanned.emit(items)


class MediaModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows: list[MediaItem] = []
        self.headings = ['Тип', 'Назва']

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headings[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        item = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                '📷' if item.kind == 'photo' else '▶',
                display_media_name(item.name),
            ][index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.path
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 0:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def replace(self, items: list[MediaItem]):
        self.beginResetModel()
        self.rows = items
        self.endResetModel()

    def item_at(self, row: int) -> MediaItem | None:
        return self.rows[row] if 0 <= row < len(self.rows) else None


class PlayerSurface(QWidget):
    """Single capture surface with strict single-player audio ownership.

    Qt's media loading is asynchronous. Reusing an old QMediaPlayer immediately
    after stop() may leave a buffered audio backend audible during a fast switch.
    Mute, stop, detach, clear and retire the OLD engine before creating a new one.
    """
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackStateChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self._volume = 1.0
        self._muted = False
        self._playback_rate = 1.0
        self.player: QMediaPlayer | None = None
        self.audio: QAudioOutput | None = None
        self.current: MediaItem | None = None
        self.setStyleSheet('background:black;')
        self.stack = QStackedWidget()
        self.stack.setStyleSheet('background:black;')
        self.black = QLabel('')
        self.black.setStyleSheet('background:black;')
        self.video_view = FitVideoViewport()
        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self.video_view.observe_frame)
        self.photo = AspectImage()
        self.stack.addWidget(self.black)
        self.stack.addWidget(self.video_view)
        self.stack.addWidget(self.photo)
        container = QVBoxLayout(self)
        container.setContentsMargins(0, 0, 0, 0)
        container.addWidget(self.stack)
        self._create_player()

    def _create_player(self):
        player = QMediaPlayer(self)
        self.player = player
        player.setVideoSink(self.video_sink)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self._volume)
        self.audio.setMuted(self._muted)
        player.setAudioOutput(self.audio)
        player.setPlaybackRate(self._playback_rate)
        # Bind signals to their owner. Status callbacks queued by an old engine
        # must never interrupt a newly playing file.
        player.mediaStatusChanged.connect(
            lambda status, source=player: self._emit_current(source, self.mediaStatusChanged, status)
        )
        player.errorOccurred.connect(
            lambda error, description, source=player: self._emit_current(
                source, self.errorOccurred, error, description
            )
        )
        player.positionChanged.connect(
            lambda position, source=player: self._emit_current(source, self.positionChanged, position)
        )
        player.durationChanged.connect(
            lambda duration, source=player: self._emit_current(source, self.durationChanged, duration)
        )
        player.playbackStateChanged.connect(
            lambda state, source=player: self._emit_current(source, self.playbackStateChanged, state)
        )

    def _emit_current(self, source, signal, *args):
        if self.player is source:
            signal.emit(*args)

    def _release_player(self):
        old, old_audio = self.player, self.audio
        # Invalidate all previous callbacks BEFORE stopping the player.
        self.player = None
        self.audio = None
        if old_audio is not None:
            old_audio.setMuted(True)
            old_audio.setVolume(0.0)
        if old is not None:
            old.stop()
            old.setSource(QUrl())  # Release decoder/source I/O
            old.setAudioOutput(None)
            old.setVideoOutput(None)
            old.deleteLater()
        if old_audio is not None:
            old_audio.deleteLater()

    def _restart_player(self):
        self._release_player()
        self._create_player()

    def set_volume(self, value: float):
        self._volume = max(0.0, min(1.0, float(value)))
        if self.audio is not None:
            self.audio.setVolume(self._volume)

    def set_muted(self, muted: bool):
        self._muted = bool(muted)
        if self.audio is not None:
            self.audio.setMuted(self._muted)

    def set_playback_rate(self, rate: float):
        if rate not in SPEED_PRESETS:
            raise ValueError('Непідтримувана швидкість відтворення')
        self._playback_rate = float(rate)
        if self.player is not None:
            self.player.setPlaybackRate(self._playback_rate)

    def set_position(self, value: int):
        if self.player is not None:
            self.player.setPosition(value)

    def play_item(self, item: MediaItem):
        self.current = None
        self.stack.setCurrentWidget(self.black)
        self._restart_player()
        self.video_view.forced_portrait = False
        self.video_view.reset_crop()
        if item.kind == 'photo':
            if self.photo.set_file(item.path):
                self.current = item
                self.stack.setCurrentWidget(self.photo)
                return True
            self.black_out()
            return False
        self.current = item
        self.stack.setCurrentWidget(self.video_view)
        self.player.setSource(QUrl.fromLocalFile(item.path))
        # Some multimedia backends reset speed when a new source is loaded.
        self.player.setPlaybackRate(self._playback_rate)
        self.player.play()
        return True

    def black_out(self):
        self.current = None
        self.stack.setCurrentWidget(self.black)
        self.photo.clear_image()
        self.video_view.reset_crop()
        # Destroy even paused and buffered engines; no previous audio survives.
        self._restart_player()

    def shutdown(self):
        self.current = None
        self.stack.setCurrentWidget(self.black)
        self._release_player()


class UpdateThread(QThread):
    checked = Signal(object)
    downloaded = Signal(object)
    progress = Signal(int)
    failed = Signal(str)

    def __init__(self, action: str, release: dict | None = None):
        super().__init__()
        self.action = action
        self.release = release

    def run(self):
        try:
            if self.action == 'check':
                self.checked.emit(updater.fetch_latest(VERSION))
            else:
                self.downloaded.emit(updater.download_update(
                    self.release, self.progress.emit, self.isInterruptionRequested))
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdatesDialog(QDialog):
    def __init__(self, parent, install_callback):
        super().__init__(parent)
        self.setWindowTitle('Налаштування - Оновлення RG Media Deck')
        self.setMinimumWidth(520)
        self.release = None
        self.staged = None
        self.worker = None
        self.install_callback = install_callback
        layout = QVBoxLayout(self)
        layout.setSpacing(13)
        self.version_info = QLabel(f'Поточна версія: {VERSION}')
        self.version_info.setStyleSheet('font-size:16px; font-weight:700;')
        layout.addWidget(self.version_info)
        self.info = QLabel('Оновлення програми. Бібліотека та налаштування не видаляються.')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.check_btn = make_button('↻ Перевірити оновлення', self.check_updates)
        layout.addWidget(self.check_btn)
        self.download_btn = make_button('⬇ Завантажити оновлення', self.download)
        self.download_btn.setEnabled(False)
        layout.addWidget(self.download_btn)
        self.install_btn = make_button('✓ Встановити та перезапустити', self.install)
        self.install_btn.setEnabled(False)
        layout.addWidget(self.install_btn)
        self.state = QLabel('Не оновлюйте програму під час стріму: показ в OBS тимчасово зупиниться.')
        self.state.setWordWrap(True)
        self.state.setObjectName('Muted')
        layout.addWidget(self.state)
        self.cancel_btn = make_button('Закрити', self.reject)
        layout.addWidget(self.cancel_btn)

    def _work(self, kind: str):
        self.check_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.worker = UpdateThread(kind, self.release)
        self.worker.checked.connect(self.on_checked)
        self.worker.downloaded.connect(self.on_downloaded)
        self.worker.progress.connect(lambda p: self.state.setText(f'Завантаження: {p}%'))
        self.worker.failed.connect(self.on_error)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def check_updates(self):
        self.release = None
        self.staged = None
        self.state.setText('Перевіряю GitHub Releases...')
        self._work('check')

    def on_checked(self, release):
        self.release = release
        if release is None:
            self.info.setText(f'Встановлена актуальна версія: {VERSION}')
            self.state.setText('Нових випусків RG Media Deck немає.')
        else:
            self.info.setText(f'Доступна версія {release["version"]}\n' + release.get('notes', '')[:400])
            self.state.setText('Нова версія доступна. Натисніть «Завантажити».')

    def download(self):
        self.state.setText('Завантаження нової версії...')
        self._work('download')

    def on_downloaded(self, outcome):
        self.staged = outcome  # (path, SHA256)
        self.state.setText('Інсталятор перевірено (SHA256). Можна оновлювати.')

    def on_error(self, message):
        self.state.setText('Помилка: ' + message)

    def on_finished(self):
        self.worker = None
        self.check_btn.setEnabled(True)
        self.download_btn.setEnabled(self.release is not None and self.staged is None)
        self.install_btn.setEnabled(self.staged is not None)

    def install(self):
        if not self.staged or not self.release:
            return
        if QMessageBox.question(self, 'Оновлення',
                'Програма закриється, оновиться та запуститься знову. Показ в OBS перерветься.\n'
                'Запускати оновлення?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.install_callback(self.staged[0], self.staged[1], self.release['version'])
        except Exception as exc:
            QMessageBox.critical(self, 'Не вдалося підготувати оновлення', str(exc))
        else:
            self.accept()

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.state.setText('Завершую поточну операцію...')
            return
        super().reject()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.roots = list(dict.fromkeys(self.settings['roots']))
        self.favorites = set(normalize_path(x) for x in self.settings['favorites'])
        self.all_media: list[MediaItem] = []
        self.selected: MediaItem | None = None
        self.scanner: ScanThread | None = None
        self._pending_rescan = False
        self.setWindowTitle(f'RG MEDIA DECK {VERSION} | Пульт ефіру')
        self.resize(1460, 850)
        self.setMinimumSize(1050, 620)
        self.setStyleSheet(STYLE)
        self._init_ui()
        self._shortcuts()
        if self.roots:
            QTimer.singleShot(250, self.scan)
        else:
            QTimer.singleShot(250, self.add_folder)

    def open_settings(self):
        dialog = UpdatesDialog(self, self._install_update)
        dialog.setStyleSheet(STYLE)
        dialog.exec()

    def open_actions_menu(self):
        """All previously top-row controls are now near the favorite button."""
        menu = QMenu(self)
        add = menu.addAction('＋ Додати папку...')
        folders = menu.addAction('▣ Папки медіатеки...')
        refresh = menu.addAction('↻ Оновити медіатеку (F5)')
        menu.addSeparator()
        auto = menu.addAction('Автоматично прибирати чорні поля (Z)')
        auto.setCheckable(True)
        auto.setChecked(self.preview.video_view.auto_crop)
        menu.addSeparator()
        updates = menu.addAction('⚙ Налаштування та оновлення програми...')
        choice = menu.exec(self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft()))
        if choice == add:
            self.add_folder()
        elif choice == folders:
            self.manage_folders()
        elif choice == refresh:
            self.scan()
        elif choice == auto:
            self.set_auto_crop(auto.isChecked())
        elif choice == updates:
            self.open_settings()

    def _install_update(self, staged: Path, sha256: str, version: str):
        command = updater.prepare_installer(Path(staged), sha256, version)
        if self.scanner and self.scanner.isRunning():
            raise RuntimeError('Зачекайте завершення сканування перед встановленням')
        # Inno Setup installs the next version without a console; close this app first.
        subprocess.Popen(command, cwd=str(Path(command[0]).parent),
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                         close_fds=True)
        QTimer.singleShot(0, self.close)

    def _panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName('Panel')
        return frame

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(8)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        left = self._panel()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(11, 11, 11, 9)
        lv.setSpacing(8)
        heading = QLabel('ФАКТАЖ ПРОЄКТУ РАША ГУДБАЙ')
        heading.setObjectName('SectionTitle')
        lv.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText('🔎 Пошук за назвою файлу...')
        self.search.setClearButtonEnabled(True)
        lv.addWidget(self.search)
        controls = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem('Усі файли', 'all')
        self.kind.addItem('Відео / аудіо', 'video')
        self.kind.addItem('Фото', 'photo')
        controls.addWidget(self.kind)
        self.only_favorites = QCheckBox('★ Обране')
        controls.addWidget(self.only_favorites)
        controls.addStretch(1)
        lv.addLayout(controls)
        self.model = MediaModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().resizeSection(0, 52)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lv.addWidget(self.table, 1)
        self.count = QLabel('Файлів: 0')
        self.count.setStyleSheet('color:#abb0b9; font-size:11px;')
        lv.addWidget(self.count)
        split.addWidget(left)

        right = self._panel()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 10, 10, 10)
        rv.setSpacing(6)
        preview_head = QHBoxLayout()
        h = QLabel('ПОПЕРЕДНІЙ ПЕРЕГЛЯД')
        h.setObjectName('SectionTitle')
        preview_head.addWidget(h)
        self.file_title = ElidedLabel('Файл не обрано')
        self.file_title.setObjectName('SelectedFilename')
        preview_head.addWidget(self.file_title, 1)
        self.star = make_button('☆ В обране', self.toggle_favorite)
        preview_head.addWidget(self.star)
        self.settings_btn = make_button('⚙', self.open_actions_menu)
        self.settings_btn.setObjectName('SettingsGear')
        self.settings_btn.setFixedSize(34, 32)
        self.settings_btn.setAccessibleName('Налаштування та керування медіатекою')
        self.settings_btn.setToolTip('Налаштування, папки та оновлення')
        preview_head.addWidget(self.settings_btn)
        rv.addLayout(preview_head)
        self.preview = PlayerSurface()
        self.preview.set_volume(self.settings['volume'] / 100)
        self.preview.set_muted(self.settings['muted'])
        self.preview.set_playback_rate(self.settings['playback_rate'])
        self.preview.video_view.set_auto_crop(self.settings['auto_crop'])
        self.preview.video_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.preview.black.setText('Оберіть фото або відео з бібліотеки')
        self.preview.black.setStyleSheet('background:#000; color:#999aa0;')
        self.preview.setMinimumHeight(300)
        rv.addWidget(self.preview, 1)
        timeline = QHBoxLayout()
        timeline.setSpacing(8)
        self.preview_seek = QSlider(Qt.Orientation.Horizontal)
        self.preview_seek.setRange(0, 0)
        self.preview_seek.setFixedHeight(20)
        timeline.addWidget(self.preview_seek, 1)
        self.preview_time = QLabel('00:00 / 00:00')
        self.preview_time.setStyleSheet('color:#c4c8d0; font-size:12px; min-width:92px;')
        timeline.addWidget(self.preview_time)
        rv.addLayout(timeline)

        # Exactly one compact transport row: combined play/pause, stop, mute,
        # volume and speed. Reserve the remaining vertical space for OBS capture.
        self.control_row = QWidget()
        self.control_row.setObjectName('TransportRow')
        self.control_row.setStyleSheet('QWidget#TransportRow { background:transparent; border:0; }')
        transport = QHBoxLayout(self.control_row)
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(6)
        self.preview_play = make_button('▶', self.toggle_preview, 'PlayButton')
        self.preview_stop = make_button('■', self.stop_playback, 'StopButton')
        for button, hint in (
            (self.preview_play, 'Відтворення / пауза (Пробіл)'),
            (self.preview_stop, 'Зупинити відтворення (S)'),
        ):
            button.setFixedSize(52, 34)
            button.setToolTip(hint)
            transport.addWidget(button)
        self.mute_button = make_button('', self.toggle_mute, 'MuteButton')
        self.mute_button.setCheckable(True)
        self.mute_button.setFixedSize(102, 34)
        transport.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(self.settings['volume'])
        self.volume.setFixedHeight(34)
        self.volume.setMinimumWidth(68)
        transport.addWidget(self.volume, 1)
        self.vol_value = QLabel(f'{self.settings["volume"]}%')
        self.vol_value.setFixedWidth(36)
        self.vol_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vol_value.setStyleSheet('font-size:12px; color:#d1d4db;')
        transport.addWidget(self.vol_value)
        self.speed_slower = make_button('−', lambda: self.step_speed(-1), 'SpeedStep')
        self.speed_slower.setFixedSize(30, 34)
        self.speed_slower.setToolTip('Уповільнити')
        transport.addWidget(self.speed_slower)
        self.speed_selector = QComboBox()
        for speed in SPEED_PRESETS:
            self.speed_selector.addItem(f'{speed:g}×', speed)
        self.speed_selector.setCurrentIndex(SPEED_PRESETS.index(self.settings['playback_rate']))
        self.speed_selector.setFixedSize(74, 34)
        self.speed_selector.setToolTip('Швидкість відтворення')
        transport.addWidget(self.speed_selector)
        self.speed_faster = make_button('+', lambda: self.step_speed(1), 'SpeedStep')
        self.speed_faster.setFixedSize(30, 34)
        self.speed_faster.setToolTip('Прискорити')
        transport.addWidget(self.speed_faster)
        rv.addWidget(self.control_row)
        self._refresh_mute_button()
        self._refresh_speed_buttons()
        split.addWidget(right)
        split.setSizes([520, 920])
        self.status = QLabel('Готово до відтворення.')
        self.status.setObjectName('Status')
        root.addWidget(self.status)

        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(120)
        self.filter_timer.timeout.connect(self.apply_filter)
        self.search.textChanged.connect(self.filter_timer.start)
        self.kind.currentIndexChanged.connect(self.apply_filter)
        self.only_favorites.toggled.connect(self.apply_filter)
        self.table.selectionModel().currentRowChanged.connect(self.selection_changed)
        self.table.doubleClicked.connect(lambda _: self.play_selected())
        self.table.customContextMenuRequested.connect(self.show_file_context_menu)
        self.preview.video_view.customContextMenuRequested.connect(self.show_video_context_menu)
        self.preview.positionChanged.connect(self.preview_progress)
        self.preview.durationChanged.connect(self.preview_duration)
        self.preview_seek.sliderMoved.connect(self.preview.set_position)
        self.preview.errorOccurred.connect(self._preview_error)
        self.preview.mediaStatusChanged.connect(self._preview_media_status)
        self.preview.playbackStateChanged.connect(self._update_play_button)
        self.volume.valueChanged.connect(self.volume_changed)
        self.speed_selector.currentIndexChanged.connect(self.speed_changed)
        self._update_play_button()

    def _shortcuts(self):
        for sequence, callback in [
            ('Ctrl+F', self.search.setFocus),
            ('Ctrl+Return', self.play_selected),
            ('Escape', self.stop_playback),
            ('F5', self.scan),
            ('Ctrl+P', self.toggle_preview),
            ('Ctrl+O', self.add_folder),
        ]:
            sc = QShortcut(QKeySequence(sequence), self)
            sc.activated.connect(callback)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.KeyPress or QApplication.activeModalWidget():
            return super().eventFilter(watched, event)
        focus = QApplication.focusWidget()
        # Never hijack typing, combo popup selection or slider adjustments.
        if isinstance(focus, (QLineEdit, QComboBox, QSlider, QPushButton)):
            return super().eventFilter(watched, event)
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        on_table = bool(focus is self.table or (focus and self.table.isAncestorOf(focus)))
        if key == Qt.Key.Key_Space and not ctrl:
            self.toggle_preview()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl:
            self.play_selected()
        elif key == Qt.Key.Key_M and not ctrl:
            self.toggle_mute()
        elif key == Qt.Key.Key_S and not ctrl:
            self.stop_playback()
        elif key == Qt.Key.Key_Delete and on_table:
            item = self.model.item_at(self.table.currentIndex().row())
            if item:
                self.confirm_delete_file(item)
            else:
                return False
        elif key == Qt.Key.Key_Z and not ctrl:
            self.set_auto_crop(not self.preview.video_view.auto_crop)
        elif key == Qt.Key.Key_V and not ctrl:
            self.preview.video_view.set_forced_portrait(not self.preview.video_view.forced_portrait)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) and not ctrl:
            self.step_speed(1)
        elif key == Qt.Key.Key_Minus and not ctrl:
            self.step_speed(-1)
        elif key == Qt.Key.Key_0 and not ctrl:
            self.speed_selector.setCurrentIndex(SPEED_PRESETS.index(1.0))
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and (ctrl or not on_table):
            self.seek_relative((1 if key == Qt.Key.Key_Right else -1) * (30000 if shift else 5000))
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not on_table:
            self.volume.setValue(max(0,min(100,self.volume.value() + (5 if key == Qt.Key.Key_Up else -5))))
        elif key == Qt.Key.Key_Home and not on_table:
            self.preview.set_position(0)
        elif key == Qt.Key.Key_End and not on_table and self.preview.player:
            self.preview.set_position(max(0,self.preview.player.duration() - 800))
        else:
            return super().eventFilter(watched, event)
        event.accept()
        return True

    def seek_relative(self, milliseconds: int):
        if self.preview.current and self.preview.current.kind == 'video' and self.preview.player:
            player = self.preview.player
            player.setPosition(max(0,min(player.duration(),player.position() + milliseconds)))

    def _save(self):
        try:
            save_settings({
                'roots': self.roots,
                'favorites': sorted(self.favorites),
                'volume': self.volume.value(),
                'muted': self.mute_button.isChecked(),
                'playback_rate': self.speed_selector.currentData(),
                'auto_crop': self.preview.video_view.auto_crop,
            })
        except OSError as exc:
            self.status.setText(f'Налаштування не збережені: {exc}')

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Оберіть папку з фото та відео')
        if not folder:
            return
        existing = {normalize_path(x) for x in self.roots}
        if normalize_path(folder) not in existing:
            self.roots.append(folder)
            self._save()
        self.scan()

    def manage_folders(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Папки медіатеки')
        dialog.setText('Папки сканування:\n\n' + ('\n'.join(self.roots) if self.roots else '(порожньо)'))
        dialog.setInformativeText('Щоб прибрати папку, виберіть «Вилучити» і введіть її номер у наступному вікні.')
        add_btn = dialog.addButton('Додати папку', QMessageBox.ButtonRole.ActionRole)
        remove_btn = dialog.addButton('Вилучити папку', QMessageBox.ButtonRole.ActionRole)
        dialog.addButton('Закрити', QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() == add_btn:
            self.add_folder()
        elif dialog.clickedButton() == remove_btn and self.roots:
            from PySide6.QtWidgets import QInputDialog
            choice, ok = QInputDialog.getItem(self, 'Вилучити папку', 'Папка:', self.roots, 0, False)
            if ok and choice in self.roots:
                self.roots.remove(choice)
                self._save()
                self.scan()

    def scan(self):
        if self.scanner is not None and self.scanner.isRunning():
            self._pending_rescan = True
            self.scanner.requestInterruption()
            self.status.setText('Зупиняю поточне сканування для нового запуску...')
            return
        self._pending_rescan = False
        self.status.setText('Сканування папок...')
        self.scanner = ScanThread(self.roots)
        self.scanner.counted.connect(lambda n: self.status.setText(f'Знайдено {n} файлів...'))
        self.scanner.scanned.connect(self.scan_complete)
        self.scanner.finished.connect(self.scan_finished)
        self.scanner.start()

    def scan_finished(self):
        if self._pending_rescan:
            self._pending_rescan = False
            QTimer.singleShot(0, self.scan)
        elif self.scanner and self.scanner.isInterruptionRequested():
            self.status.setText('Сканування зупинене')

    def scan_complete(self, items: list[MediaItem]):
        self.all_media = items
        self.apply_filter()
        self.status.setText(f'Бібліотека оновлена: {len(items)} медіафайлів. Файли на диску не змінено.')

    def apply_filter(self):
        old_path = self.selected.path if self.selected else None
        filtered = filter_media(self.all_media, self.search.text(), self.kind.currentData(),
                                self.favorites, self.only_favorites.isChecked())
        self.model.replace(filtered)
        self.count.setText(f'Показано: {len(filtered)}   •   Усього: {len(self.all_media)}')
        # Filtering must not trigger selection_changed or interrupt the playing file.
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.table.selectionModel()):
            if old_path:
                for idx, item in enumerate(filtered):
                    if item.path == old_path:
                        self.table.selectRow(idx)
                        break
        # The current audio/video remains untouched until a deliberate click.

    def selection_changed(self, current: QModelIndex, previous: QModelIndex):
        item = self.model.item_at(current.row()) if current.isValid() else None
        if not item:
            return
        self.selected = item
        self.file_title.setText(display_media_name(item.name))
        self.file_title.setToolTip(item.path)
        self.star.setText('★ В обраному' if normalize_path(item.path) in self.favorites else '☆ В обране')
        self.play_selected()

    def toggle_favorite(self):
        if self.selected:
            self.toggle_favorite_item(self.selected)

    def toggle_favorite_item(self, item: MediaItem):
        normalized = normalize_path(item.path)
        if normalized in self.favorites:
            self.favorites.remove(normalized)
        else:
            self.favorites.add(normalized)
        self._save()
        self.apply_filter()
        if self.selected and self.selected.path == item.path:
            self.star.setText('★ В обраному' if normalized in self.favorites else '☆ В обране')

    def show_file_context_menu(self, pos):
        index = self.table.indexAt(pos)
        item = self.model.item_at(index.row()) if index.isValid() else None
        if item is None:
            return
        menu = QMenu(self)
        delete_action = menu.addAction('Видалити файл')
        key = normalize_path(item.path)
        favorite_action = menu.addAction('Прибрати з обраного' if key in self.favorites else 'Додати в обране')
        reveal_action = menu.addAction('Показати розташування')
        choice = menu.exec(self.table.viewport().mapToGlobal(pos))
        if choice == delete_action:
            self.confirm_delete_file(item)
        elif choice == favorite_action:
            self.toggle_favorite_item(item)
        elif choice == reveal_action:
            self.reveal_file(item)

    def reveal_file(self, item: MediaItem):
        if os.name == 'nt':
            subprocess.Popen(['explorer.exe', '/select,', os.path.normpath(item.path)],
                             close_fds=True)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(item.path).parent)))

    def confirm_delete_file(self, item: MediaItem):
        if QMessageBox.question(self, 'Видалити файл?',
                f'Перемістити файл до кошика Windows?\n\n{item.name}\n\n'
                'Файл буде вилучено також з вихідної папки.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        # Windows will refuse moving a video while its decoder owns the file.
        if self.preview.current and normalize_path(self.preview.current.path) == normalize_path(item.path):
            self.stop_playback()
        self.status.setText('Переміщення файлу до кошика...')
        QTimer.singleShot(250, lambda: self._delete_file_from_disk(item))

    def _delete_file_from_disk(self, item: MediaItem):
        try:
            send2trash(item.path)
        except Exception as exc:
            QMessageBox.warning(self, 'Файл не видалено', str(exc))
            self.status.setText('Не вдалося перемістити файл до кошика')
            return
        normalized = normalize_path(item.path)
        self.favorites.discard(normalized)
        self.all_media = [f for f in self.all_media if normalize_path(f.path) != normalized]
        if self.selected and normalize_path(self.selected.path) == normalized:
            self.selected = None
            self.file_title.setText('Файл не обрано')
            self.star.setText('☆ В обране')
        self._save()
        self.apply_filter()
        self.status.setText(f'Файл переміщено до кошика: {display_media_name(item.name)}')

    def show_video_context_menu(self, pos):
        menu = QMenu(self)
        mode = menu.addAction('Автоматично прибирати чорні поля (Z)')
        mode.setCheckable(True)
        mode.setChecked(self.preview.video_view.auto_crop)
        portrait = menu.addAction('Вертикальний кадр 9:16 (V)')
        portrait.setCheckable(True)
        portrait.setChecked(self.preview.video_view.forced_portrait)
        choice = menu.exec(self.preview.video_view.mapToGlobal(pos))
        if choice == mode:
            self.set_auto_crop(mode.isChecked())
        elif choice == portrait:
            self.preview.video_view.set_forced_portrait(portrait.isChecked())
            self.status.setText('Вертикальне кадрування 9:16' if portrait.isChecked() else 'Стандартне кадрування')

    def set_auto_crop(self, enabled: bool):
        self.preview.video_view.set_auto_crop(enabled)
        self._save()
        self.status.setText('Автокадрування увімкнено' if enabled else 'Автокадрування вимкнено')

    def _update_play_button(self, *_):
        player = self.preview.player
        playing = bool(player and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.preview_play.setText('Ⅱ' if playing else '▶')
        self.preview_play.setToolTip('Пауза (Пробіл)' if playing else 'Відтворення (Пробіл)')

    def toggle_preview(self):
        player = self.preview.player
        if player is None or self.preview.current is None or self.preview.current.kind == 'photo':
            return
        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause_playback()
        else:
            self.play_selected()

    def pause_playback(self):
        player = self.preview.player
        if player is not None and self.preview.current and self.preview.current.kind == 'video':
            if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                player.pause()
                self._update_play_button()
                self.status.setText('Пауза')

    def preview_progress(self, position: int):
        if not self.preview_seek.isSliderDown():
            self.preview_seek.setValue(position)
        duration = self.preview.player.duration() if self.preview.player is not None else 0
        self.preview_time.setText(f'{timestamp(position)} / {timestamp(duration)}')

    def preview_duration(self, duration: int):
        self.preview_seek.setRange(0, max(0, duration))
        position = self.preview.player.position() if self.preview.player is not None else 0
        self.preview_progress(position)

    def play_selected(self):
        if not self.selected:
            self.status.setText('Спочатку оберіть файл у медіатеці.')
            return
        if not os.path.isfile(self.selected.path):
            self.status.setText('Файл не знайдено. Оновіть бібліотеку.')
            return
        # PLAY resumes the currently selected paused file without seeking to zero.
        if (self.preview.current is not None and self.preview.current.path == self.selected.path
                and self.selected.kind == 'video' and self.preview.player is not None):
            self.preview.player.play()
            self._update_play_button()
            self.status.setText(f'Відтворюється: {display_media_name(self.selected.name)}')
            return
        self.preview_seek.setValue(0)
        self.preview_seek.setEnabled(self.selected.kind == 'video')
        if not self.preview.play_item(self.selected):
            self.status.setText('Не вдалося відкрити медіафайл.')
            return
        self.status.setText(f'Відтворюється: {display_media_name(self.selected.name)}')
        self._update_play_button()

    def stop_playback(self):
        self.preview.black_out()
        self.preview.black.setText('')
        self.preview_seek.setValue(0)
        self.preview_time.setText('00:00 / 00:00')
        self.status.setText('Відтворення зупинено')
        self._update_play_button()

    def _refresh_mute_button(self):
        muted = self.preview._muted
        self.mute_button.setChecked(muted)
        self.mute_button.setText('ЗВУК ВИМК.' if muted else 'ГУЧНІСТЬ')
        self.mute_button.setToolTip('Увімкнути звук' if muted else 'Вимкнути звук')
        self.mute_button.setAccessibleName('Перемикач гучності')

    def toggle_mute(self):
        self.preview.set_muted(not self.preview._muted)
        self._refresh_mute_button()
        self._save()

    def volume_changed(self, value: int):
        self.preview.set_volume(value / 100)
        self.vol_value.setText(f'{value}%')
        self._save()

    def step_speed(self, direction: int):
        index = max(0, min(len(SPEED_PRESETS) - 1, self.speed_selector.currentIndex() + direction))
        self.speed_selector.setCurrentIndex(index)

    def speed_changed(self, index: int):
        if index < 0:
            return
        self.preview.set_playback_rate(self.speed_selector.itemData(index))
        self._refresh_speed_buttons()
        self._save()

    def _refresh_speed_buttons(self):
        index = self.speed_selector.currentIndex()
        self.speed_slower.setEnabled(index > 0)
        self.speed_faster.setEnabled(index < len(SPEED_PRESETS) - 1)

    def _preview_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop_playback()

    def _preview_error(self, error, description):
        if error != QMediaPlayer.Error.NoError:
            self.status.setText(f'ПОМИЛКА відтворення: {description}')
            logging.error('Preview media error: %s', description)

    def closeEvent(self, event):
        if self.scanner and self.scanner.isRunning():
            self.scanner.requestInterruption()
            if not self.scanner.wait(1500):
                self.status.setText('Сканування завершується. Спробуйте закрити ще раз.')
                event.ignore()
                return
        self._save()
        QApplication.instance().removeEventFilter(self)
        self.preview.shutdown()
        event.accept()


def main():
    logging.basicConfig(
        filename=str(settings_path().parent / 'app.log') if settings_path().parent.exists() else None,
        level=logging.WARNING,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    app = QApplication(sys.argv)
    app.setApplicationName('RG Media Deck')
    app.setStyle('Fusion')
    if '--selftest' in sys.argv:
        surface = PlayerSurface()
        passed = surface.player is not None and surface.audio is not None
        surface.shutdown()
        dialog = UpdatesDialog(None, lambda *args: None)
        passed = passed and dialog.version_info.text().endswith(VERSION)
        # Verify the new UI has just two library columns, one capture surface.
        model = MediaModel()
        passed = passed and model.columnCount() == 2
        # The dedicated broadcast window was removed; the main capture area owns audio.
        passed = passed and not hasattr(surface, 'preview')
        passed = passed and surface.audio is None  # shutdown released audio ownership
        dialog.close()
        if passed:
            main_window = MainWindow()
            passed = (main_window.preview_play.height() <= 36
                and main_window.preview_stop.height() <= 36
                and not hasattr(main_window, 'preview_pause')
                and main_window.preview_play.parentWidget() is main_window.control_row
                and main_window.preview_stop.parentWidget() is main_window.control_row
                and main_window.mute_button.parentWidget() is main_window.control_row
                and main_window.speed_selector.parentWidget() is main_window.control_row
                and not hasattr(main_window, 'file_path')
                and main_window.mute_button.isCheckable()
                and main_window.speed_selector.count() == len(SPEED_PRESETS)
                and not hasattr(main_window, 'repeat')
                and not hasattr(main_window, 'file_black_button')
                and main_window.table.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
                and main_window.preview.video_view.auto_crop
                and main_window.preview.video_sink is not None
                and not hasattr(main_window.preview.video_view, 'video')
                and not hasattr(main_window, 'rescan_button')
                and not hasattr(main_window, 'header_toolbar')
                and main_window.settings_btn.parentWidget() is not None)
            main_window.preview.set_playback_rate(1.5)
            main_window.preview.set_muted(True)
            passed = passed and main_window.preview._playback_rate == 1.5
            passed = passed and main_window.preview._muted
            main_window.toggle_mute()
            passed = passed and not main_window.preview._muted
            main_window.step_speed(1)
            passed = passed and main_window.speed_selector.currentData() == 1.25
            passed = passed and display_media_name('Назва відео.mp4') == 'Назва відео'
            main_window.preview.shutdown()
            main_window.close()
        return 0 if passed else 1
    window = MainWindow()
    window.show()
    if '--post-update-health' in sys.argv:
        index = sys.argv.index('--post-update-health')
        if index + 1 < len(sys.argv):
            marker_path = Path(sys.argv[index + 1])
            QTimer.singleShot(100, lambda: marker_path.write_text(VERSION, encoding='utf-8'))
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
