RG Repair V2: Release Health
Scope: rg_release_health_gate.py only.
Use AFTER successful installation of RG Repair V1.

1. Close Studio normally (do not kill processes).
2. Run INSTALL_RELEASE_HEALTH_V2.cmd from extracted package.
3. Check INSTALLED result. A hash-verified backup is saved in
   F:\RG_AUTO_EDIT\RG Auto Edit Data\RG_REPAIR_BACKUPS.
4. Open Studio; run QA-only for 891 and 898. Do not re-montage.
5. To restore: close Studio then run ROLLBACK_RELEASE_HEALTH_V2.cmd.

Scope of fix: a single R2 revision is accepted ONLY when matching current
manifest, index and screenshot. Real missing 904-3 and all overlap/audio
protections remain in force; 904 must not be auto-exported or called PASS.
915 needs a separate run through the GUI with V1 synchronized audio.
908 lacks screenshots on NAS; no frames are fabricated.
