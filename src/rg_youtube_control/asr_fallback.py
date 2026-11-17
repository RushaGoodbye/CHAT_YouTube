"""Bounded offline Whisper fallback for videos whose public captions are blocked.

Runs under the operator's Python 3.12, not the frozen GUI. Exact YouTube ID
audio input only, no fuzzy local file matching and no YouTube Data API writes.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .batch_seo_pipeline import (
    VIDEO_ID, _candidates, _seconds, _write_atomic, inspect_srt, srt_text,
    inspect_seo_draft,
)


def gpu_capacity() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True
        )
        line = result.stdout.splitlines()[0]
        utilization, available = [int(x.strip()) for x in line.split(",")[:2]]
        if utilization > 25 or available < 9000:
            return False, f"GPU busy: utilization={utilization}% free={available}MiB"
        return True, f"GPU available: utilization={utilization}% free={available}MiB"
    except Exception as exc:
        return False, f"GPU check failed: {type(exc).__name__}"


def _whisper_model():
    """Resolve CUDA runtime from existing PyTorch, without changing Auto Edit."""
    if os.name == "nt":
        torch_lib = Path(sys.prefix) / "Lib" / "site-packages" / "torch" / "lib"
        if not torch_lib.is_dir():
            raise RuntimeError("PyTorch CUDA runtime directory missing")
        os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ["PATH"]
        # Keep DLL directory handle alive for the entire model lifetime.
        handle = os.add_dll_directory(str(torch_lib))
        libraries = [
            ctypes.WinDLL(str(torch_lib / name)) for name in
            ("cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll")
        ]
    else:
        handle, libraries = None, []
    import torch  # noqa: F401 - registers CUDA runtime used by CTranslate2
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3", device="cuda",
                         compute_type="int8_float16", local_files_only=True)
    return model, handle, libraries


def download_audio(video_id: str, work_dir: Path, *, max_seconds: int = 3600) -> Path:
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Invalid video id")
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / (video_id + ".mp3")
    if target.exists() and target.stat().st_size > 4096:
        return target
    ffmpeg_dir = Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin")
    if not ffmpeg_dir.is_dir():
        raise RuntimeError("FFmpeg directory missing")
    template = str(work_dir / (video_id + ".%(ext)s"))
    args = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist", "--no-warnings",
        "--socket-timeout", "15", "--retries", "1",
        "--fragment-retries", "1",
        "--ffmpeg-location", str(ffmpeg_dir),
        "-f", "bestaudio/best", "-x", "--audio-format", "mp3",
        "--audio-quality", "5", "-o", template,
        "https://www.youtube.com/watch?v=" + video_id,
    ]
    # For 1-hour content: bounded extraction time, never infinite downloads.
    completed = subprocess.run(args, capture_output=True, text=True,
                               timeout=max(180, min(900, max_seconds // 2 + 120)))
    if completed.returncode != 0:
        raise RuntimeError("audio_download_failed: " +
                           (completed.stderr or completed.stdout)[-240:])
    if not target.is_file() or target.stat().st_size < 4096:
        raise RuntimeError("downloaded_audio_missing_or_empty")
    return target


def _recent_asr_failures(folder: Path, profile: str) -> set[str]:
    blocked = set()
    if not folder.is_dir():
        return blocked
    for file in sorted(folder.glob(f"rg_asr_{profile}_*.json"), reverse=True)[:30]:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - created).total_seconds() > 86400:
                continue
            for rec in payload.get("records", []):
                if rec.get("status") in {"failed", "incomplete"}:
                    blocked.add(str(rec.get("video_id") or ""))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return blocked


def run_asr(*, db_path: str | Path, srt_dir: str | Path, temp_dir: str | Path,
            profile: str = "main", limit: int = 2,
            max_duration: int = 3600, execute: bool = False) -> dict:
    if profile not in {"main", "live"} or not 1 <= limit <= 10:
        raise ValueError("Invalid profile or limit")
    db = Path(db_path)
    target = Path(srt_dir)
    workspace = Path(temp_dir)
    if not db.is_file() or not target.is_dir():
        raise FileNotFoundError("Database or SRT directory not available")
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        candidates = _candidates(conn, profile, 100000)
        cooldown = _recent_asr_failures(target / "_batch_reports", profile)
        selected = []
        for row in candidates:
            video_id = str(row["video_id"])
            length = _seconds(row["duration"])
            if (not VIDEO_ID.fullmatch(video_id)
                or video_id in cooldown
                or length < 180 or length > max_duration):
                continue
            existing = target / (video_id + ".srt")
            if existing.exists() and existing.stat().st_size > 0:
                qc = inspect_srt(existing.read_text(
                    encoding="utf-8-sig", errors="replace"), length)
                if qc["complete"]:
                    continue
                # Never overwrite an unverified or partial existing SRT automatically.
                continue
            selected.append(row)
            if len(selected) >= limit:
                break
        records = []
        ready, gpu_note = gpu_capacity() if execute and selected else (False, "dry_run")
        if execute and selected and not ready:
            outcome = "skipped_gpu_busy"
        else:
            outcome = "ok"
        model = None
        handles = []
        for row in selected:
            vid = str(row["video_id"])
            item = {"video_id": vid, "title": str(row["title"] or ""),
                    "duration": _seconds(row["duration"]),
                    "status": "candidate", "source": "exact_video_id",
                    "error": "", "seo_result": "editorial_review_required"}
            if not execute:
                item["status"] = "dry_run"
                records.append(item)
                continue
            if not ready:
                item["status"] = "skipped_gpu_busy"
                records.append(item)
                continue
            try:
                if model is None:
                    model, dll_handle, dlls = _whisper_model()
                    handles = [dll_handle, *dlls]
                # Check again before the next large video. Model memory now
                # counts as occupied, so do not impose pre-model 9GB rule again.
                audio = download_audio(vid, workspace, max_seconds=item["duration"])
                segments, info = model.transcribe(
                    str(audio), beam_size=3, vad_filter=True,
                    condition_on_previous_text=False,
                )
                asr_rows = [
                    {"text": str(s.text).strip(), "start":float(s.start),
                     "duration": max(0.0, float(s.end)-float(s.start))}
                    for s in segments if str(s.text).strip()
                ]
                text = srt_text(asr_rows)
                inspected = inspect_srt(text, item["duration"])
                item.update(inspected)
                item["language"] = str(info.language or "")
                item["language_probability"] = round(
                    float(info.language_probability or 0), 3)
                if not inspected["complete"]:
                    item["status"] = "incomplete"
                    item["error"] = ",".join(inspected["issues"])
                else:
                    dest = target / (vid + ".srt")
                    if dest.exists():
                        item["status"] = "already_exists"
                    else:
                        _write_atomic(dest, text)
                        meta = {"video_id":vid, "profile":profile,
                                "source":"local_asr_large_v3_unverified",
                                "language":item["language"],
                                "language_probability":item["language_probability"],
                                "created_at":datetime.now(timezone.utc).isoformat(),
                                "segments":len(asr_rows), "coverage":inspected["end_coverage"],
                                "editorial_approval":False,
                                "youtube_api_units":0}
                        _write_atomic(target/(vid+".json"),json.dumps(
                            meta,ensure_ascii=False,indent=2))
                        item["status"] = "complete"
                        item.update(inspect_seo_draft(row, text))
                audio.unlink(missing_ok=True)
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = (type(exc).__name__ + ": " + str(exc))[:320]
            records.append(item)
            print(f"{len(records)}/{len(selected)} {vid}: {item['status']}",flush=True)
        result={"created_at":datetime.now(timezone.utc).isoformat(),
                "profile":profile, "dry_run":not execute, "gpu_note":gpu_note,
                "selected":len(selected),
                "status_counts":dict(Counter(rec["status"] for rec in records)),
                "youtube_data_api_units_used":0,
                "youtube_metadata_modified":False,
                "editorial_approval_automated":False, "records":records}
        reports=target/"_batch_reports"
        reports.mkdir(parents=True,exist_ok=True)
        basename=f"rg_asr_{profile}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        _write_atomic(reports/(basename+".json"),json.dumps(
            result,ensure_ascii=False,indent=2))
        with (reports/(basename+".csv")).open("w",encoding="utf-8-sig",newline="") as handle:
            keys=["video_id","title","status","source","duration","characters",
                  "segments","end_coverage","language","seo_result","seo_issues","error"]
            writer=csv.DictWriter(handle,fieldnames=keys,extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        result["report_json"]=str(reports/(basename+".json"))
        result["report_csv"]=str(reports/(basename+".csv"))
        return result
    finally:
        conn.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description="Safe local Whisper SRT fallback")
    parser.add_argument("--db",required=True)
    parser.add_argument("--srt-dir",required=True)
    parser.add_argument("--temp-dir",required=True)
    parser.add_argument("--profile",choices=("main","live"),default="main")
    parser.add_argument("--limit",type=int,default=2)
    parser.add_argument("--max-duration",type=int,default=3600)
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args(argv)
    report=run_asr(db_path=args.db,srt_dir=args.srt_dir,temp_dir=args.temp_dir,
                   profile=args.profile,limit=args.limit,max_duration=args.max_duration,
                   execute=args.execute)
    print(json.dumps({k:v for k,v in report.items() if k != "records"},
                     ensure_ascii=False,indent=2),flush=True)


if __name__ == "__main__":
    main()
