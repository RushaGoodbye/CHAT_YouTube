RG Repair V3 QA-only button fix. Requires already installed V1 and V2.
Close Studio normally. Never kill the running Studio or any workers.
Run INSTALL_QA_ONLY_V3.cmd. Its installer rejects active Studio,
active montage, running queue, unverified hashes, and creates a backup.
Open Studio. On the MONTAGE tab enter stream 891; on QA tab click
'QA БЕЗ МОНТАЖУ'. Check 10/10 PASS and queue row GOТОВО.
Repeat for 898. No full video montage is launched.
Do NOT mark 904 as ready: screenshot 904-3 was rejected.
Do NOT start 915 until source selection and processing in Studio is planned.
If anything fails, close Studio and run ROLLBACK_QA_ONLY_V3.cmd.
Backup folder: F:\RG_AUTO_EDIT\RG Auto Edit Data\RG_REPAIR_BACKUPS.
