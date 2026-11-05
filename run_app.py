"""RG YouTube Control entry point, including isolated read-only ASR QA."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def _qa_asr_local(args: list[str]) -> int:
    """Smoke-test the actual frozen installer, without touching user data."""
    if len(args) != 2:
        return 2
    source = Path(args[0]).resolve()
    output = Path(args[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / "rg_asr_frozen_smoke.json"
    try:
        from rg_youtube_control.seo_full_asr import recognize_complete_audio
        result = recognize_complete_audio(
            source=source, output_dir=output, video_id="MEitKm687xo",
            engine="whisper", model_name="large-v3",
            chunk_s=120, device="cuda", compute_type="float16",
        )
        success = (result.get("status") == "TRANSCRIBED_UNREVIEWED"
                   and result.get("all_audio_windows_processed") is True
                   and Path(result["srt_path"]).is_file()
                   and result.get("publication_allowed") is False)
        record = {"status": "PASS" if success else "FAILED",
                  "real_cuda_asr": bool(success),
                  "windows_processed": result.get("windows_processed"),
                  "duration_s": result.get("duration_s"),
                  "publication_allowed": False}
    except Exception as exc:
        record = {"status": "FAILED", "real_cuda_asr": False,
                  "error": type(exc).__name__ + ": " + str(exc)[:180],
                  "publication_allowed": False}
    report_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--rg-qa-asr-local":
        raise SystemExit(_qa_asr_local(sys.argv[2:]))
    from rg_youtube_control.main import main
    raise SystemExit(main())