from pathlib import Path
import pytest
from rg_youtube_control.seo_transcribe_local import transcribe_local_recording


def test_transcribe_requires_existing_recording(tmp_path):
    with pytest.raises(FileNotFoundError, match="recording_not_found"):
        transcribe_local_recording(tmp_path / "missing.mp4",
                                  model_directory=tmp_path / "missing_model")


def test_transcribe_requires_preinstalled_local_model(tmp_path):
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"not real media - test only validates preflight")
    with pytest.raises(FileNotFoundError, match="local_model_not_found"):
        transcribe_local_recording(media, model_directory=tmp_path / "missing_model")
