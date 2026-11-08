# RG Stability V1 — staged release candidate

This package is deliberately isolated from the installed and currently running RG Auto Edit Studio.

Implemented and testable:
- `rg_stability_readonly.py`: recovery decisions for complete XML, failed QA, incomplete checkpoints.
- `rg_errors.py`: bounded routing for recoverable QA, missing assets, and fail-closed archive damage.
- `rg_watchdog.py`: heartbeat/progress/output-activity based hang detection. Never terminates a process.
- `rg_resources.py`: advisory disk, RAM and VRAM guard with unknown-metrics state.
- `rg_xml_structural.py`: XML parse, clip boundaries, and presence of audio/video tracks; intentionally never claims full Premiere visual approval.
- `rg_output_audit.py`: output/QA evidence inventory; failed and unverified cases never become PASS.
- `rg_compact_progress.py`: opt-in PySide6 compact widget, reads snapshots only.
- `rg_nightly_report.py`: read-only status summary for the exact selected streams.

Operating constraints:
1. Only the running Studio UI can launch or resume video processing.
2. Never kill workers or automatically retry video processing from GitHub Actions.
3. Never delete or replace prior XML, MP4, revisions or state when running diagnoses.
4. Finished XML means QA-only repair is preferred, not full remountage.
5. Archive failures and source changes must stop the queue; missing optional assets are reported per stream.
6. Cigarette, smoke and bottle blur stay disabled. Notification/privacy blur stays enabled.
7. "PASS" requires explicit QA evidence. Structural XML tests are NOT visual/speaker validation.

Release gate not yet met:
- Studio integration (watchdog callback, recovery action, queue transition and mini widget).
- QA on actual completed Premiere exports, audio continuity, speaker boundaries, overlays and notification blur.
- Whole-queue acceptance and backup/rollback trial.

Do not copy these modules into the live Studio or restart Studio while the current 19-stream queue is active.

## Integration candidate (prepared; not live)

- `rg_studio_adapter.py` binds the existing Studio progress labels to a standalone compact Qt window, without launching external workers.
- `stage_studio_patch.py` builds an isolated candidate from the installed Studio UI, adding a mini-progress control and fail-closed QA check.
- `transactional_install.py` is a user-initiated, explicitly gated installer. It refuses installation while Studio runs, any video workers exist, the queue is marked running or paused, or any queue row remains pending. It preserves complete file backups and rolls back on failure.
- `test_transactional_install.py` validates blocked, dry-run, and sandbox installation with backups.
- `.github/workflows/rg-stability-v1-staged-candidate.yml` validates a candidate without editing the live Studio.
- `.github/workflows/rg-stability-adapter-offscreen.yml` verifies compact Qt UI separately.

**No automatic deployment is authorized while the 19-stream queue is running.**
Full release requires an idle, closed Studio, verification of Premiere XML and media, and explicit installed-app acceptance.
