"""Windows end-to-end switch stress using real locally generated video files.

Run as a separate process with CI timeout. No OBS needed and no user media
touched. Exercises Qt FFmpeg decoders, video/audio switching and frame paint.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from imageio_ffmpeg import get_ffmpeg_exe
from library import MediaItem
from app import PlayerSurface


def create_video(ffmpeg: str, destination: Path, rate: str, tone: int) -> None:
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-threads", "2", "-f", "lavfi", "-i",
        f"testsrc2=size=640x360:rate={rate}", "-f", "lavfi", "-i",
        f"sine=frequency={tone}:sample_rate=44100",
        "-t", "1.4", "-shortest", "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
        "-c:a", "aac", "-b:a", "64k", str(destination),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=50)
    if result.returncode:
        # Support bundled FFmpeg distributions without libx264.
        cmd[cmd.index("libx264")] = "mpeg4"
        cmd[cmd.index("-preset") : cmd.index("-preset") + 2] = []
        result = subprocess.run(cmd, capture_output=True, timeout=50)
    if result.returncode or not destination.is_file() or destination.stat().st_size < 1000:
        raise RuntimeError(f"ffmpeg fixture failed: {result.stderr.decode(errors='replace')[-1500:]}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rg_switch_stress_") as folder:
        root = Path(folder)
        ffmpeg = get_ffmpeg_exe()
        files = []
        for index, frame_rate in enumerate(("25", "30000/1001", "60", "24")):
            file = root / f"test_{index}.mp4"
            create_video(ffmpeg, file, frame_rate, 440 + 50 * index)
            files.append(MediaItem(str(file), file.name, "video", file.stat().st_size))
        photo_path = root / "news_photo.png"
        image = QImage(800, 450, QImage.Format.Format_RGB32)
        image.fill(0xFF226699)
        if not image.save(str(photo_path)):
            raise RuntimeError("Unable to make photo fixture")
        photo = MediaItem(str(photo_path), photo_path.name, "photo", photo_path.stat().st_size)

        app = QApplication.instance() or QApplication([])
        surface = PlayerSurface()
        surface.resize(720, 420)
        surface.show()
        app.processEvents()

        import psutil
        proc = psutil.Process()
        starting_threads = proc.num_threads()
        starting_ram = proc.memory_info().rss
        old_player, old_audio, old_sink = surface.player, surface.audio, surface.video_sink
        frames = []
        errors = []
        surface.video_sink.videoFrameChanged.connect(
            lambda frame: frames.append(frame.startTime()) if frame.isValid() else None)
        surface.errorOccurred.connect(lambda err, message: errors.append(message))
        max_switch_s = 0.0
        try:
            # One initial decode, so thread growth counts only subsequent swaps.
            if not surface.play_item(files[0]):
                raise RuntimeError("Initial local clip failed")
            QTest.qWait(280)
            initialized_threads = proc.num_threads()
            for i in range(120):
                item = photo if i % 13 == 0 else files[i % len(files)]
                before = time.monotonic()
                if not surface.play_item(item):
                    raise RuntimeError(f"Switch {i} refused valid file")
                duration = time.monotonic() - before
                max_switch_s = max(max_switch_s, duration)
                if surface.player is not old_player or surface.audio is not old_audio or surface.video_sink is not old_sink:
                    raise RuntimeError(f"Decoder allocated repeatedly at switch {i}")
                if surface._staged_player is not None or surface._staged_audio is not None:
                    raise RuntimeError(f"Silent second decoder detected at switch {i}")
                if duration > 1.2:
                    raise RuntimeError(f"GUI-blocking media switch: {duration:.3f}s")
                # Pump real Qt event loop so callbacks and decoder threads run.
                QTest.qWait(28 if i % 5 else 100)
            surface.play_item(files[1])
            QTest.qWait(550)
            if not frames:
                raise RuntimeError("Qt decoder did not deliver valid video frames")
            if surface.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
                raise RuntimeError("Final movie unexpectedly stopped")
            ram_growth_mb = (proc.memory_info().rss - starting_ram) / 1048576
            thread_growth = proc.num_threads() - initialized_threads
            if ram_growth_mb > 700:
                raise RuntimeError(f"Memory growth beyond 700MB: {ram_growth_mb:.1f}MB")
            if thread_growth > 30:
                raise RuntimeError(f"Decoder thread accumulation: +{thread_growth}")
            if errors:
                raise RuntimeError(f"Qt decoder errors: {errors[:4]}")
            print("RG_MEDIA_REAL_SWITCH_120_PASS "
                  f"frames={len(frames)} max_switch_ms={max_switch_s * 1000:.0f} "
                  f"memory_growth_mb={ram_growth_mb:.1f} "
                  f"threads_start={starting_threads} threads_after_warmup={initialized_threads} "
                  f"threads_growth={thread_growth}", flush=True)
        finally:
            surface.shutdown()
            surface.close()


if __name__ == "__main__":
    main()
