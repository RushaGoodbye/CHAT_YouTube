# RG_USED_DIALOGUES_V2 - persistent, reversible, no file renames
from __future__ import annotations
import json, os, time, unicodedata
from pathlib import Path
from contextlib import contextmanager

DATA_DIR = Path(os.environ.get("RG_AUTO_EDIT_DATA_DIR", r"F:\RG_AUTO_EDIT\RG Auto Edit Data"))
DB = DATA_DIR / "final_compilation_used_dialogues_v2.json"
LEGACY = DATA_DIR / "final_compilation_used_dialogues.json"

def key(path):
    return unicodedata.normalize("NFC", str(path).replace("/", "\\")).casefold()

def _read(path):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise RuntimeError(f"Registry unreadable: {path}: {exc}")

@contextmanager
def _lock():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = (DATA_DIR / "final_compilation_used_dialogues_v2.lock").open("a+b")
    try:
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()

def _load():
    obj = _read(DB)
    if obj and obj.get("schema") != "RG_USED_DIALOGUES_V2":
        raise RuntimeError("Unexpected usage registry schema")
    if not obj:
        obj = {"schema": "RG_USED_DIALOGUES_V2", "items": {}, "updated_at": 0}
    obj.setdefault("items", {})
    old = _read(LEGACY)
    obj["_legacy"] = {key(x) for x in old.get("used", [])}
    return obj

def _save(obj):
    obj.pop("_legacy", None)
    obj["updated_at"] = time.time()
    target = DB
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()

def _state(obj, path):
    k = key(path)
    rec = obj["items"].get(k, {})
    history = rec.get("history", [])
    legacy = k in obj.get("_legacy", set()) or str(path).casefold().endswith("_было.mp4")
    override = rec.get("manual_used") if "manual_used" in rec else None
    used = bool(override) if isinstance(override, bool) else bool(history or legacy)
    return {"used": used, "count": len(history), "history": history,
            "manual": override, "legacy": legacy,
            "last_output": history[-1].get("output", "") if history else "",
            "last_at": history[-1].get("at", 0) if history else 0}

def statuses(paths):
    obj = _load()
    return {str(path): _state(obj, path) for path in paths}

def status(path):
    return _state(_load(), path)

def manual_mark(paths, used):
    if not isinstance(used, bool):
        raise ValueError("used must be a bool")
    paths = list(paths)
    with _lock():
        obj = _load()
        for path in paths:
            k = key(path)
            rec = obj["items"].setdefault(k, {"path": str(path), "history": []})
            rec["path"] = str(path)
            rec["manual_used"] = used
            rec["manual_at"] = time.time()
        _save(obj)
    return len(paths)

def record_success(paths, output, job):
    output = Path(output)
    if not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError("Cannot mark usage without a completed output file")
    paths = list(paths)
    with _lock():
        obj = _load()
        count = 0
        for path in paths:
            k = key(path)
            rec = obj["items"].setdefault(k, {"path": str(path), "history": []})
            rec["path"] = str(path)
            history = rec.setdefault("history", [])
            if not any(key(h.get("output", "")) == key(output) and h.get("job") == str(job) for h in history):
                history.append({"job": str(job), "output": str(output), "at": time.time()})
                count += 1
            # A newly confirmed render supersedes any manual free override.
            rec.pop("manual_used", None)
        _save(obj)
    return count
