RG REPAIR V1 / 2026-11-09

1. Close RG Auto Edit Studio normally. Never kill Python workers.
2. Unpack the complete package on AlexPC.
3. Run INSTALL_RG_REPAIR.cmd.
4. Installation is blocked if Studio or video workers are active, or the queue is running.
5. Backup is written under F:\RG_AUTO_EDIT\RG Auto Edit Data\RG_REPAIR_BACKUPS.
6. To undo, close Studio and run ROLLBACK_RG_REPAIR.cmd.

The update DOES NOT auto-launch montage, export XML, or mark failed streams PASS.
Face evidence and real overlapping dialogue source ranges remain strict guards.
Missing screenshots for 908 need the correct input files. The 915 audio source now selects the original full-length MP4 audio ONLY when
exactly two mismatched split MP3 segments and verified embedded video/audio
start and duration are present. Otherwise it fails closed. MP3 files untouched.
QA-only validation of 891/898/904 is still required before release.

Check RG_REPAIR_REPORT.json for exact module hashes.
