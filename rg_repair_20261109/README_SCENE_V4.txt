RG Repair V4 / no-face timestamp + scene (all streams)
Requires previously installed RG Repair V1/V2/V3.

SCREENSHOT BEHAVIOUR:
  Face exists -> current strict identity process unchanged.
  No face + valid visible time + variable visual content ->
      retain temporary screenshot for independent scene lookup;
      demand scene match distinct from both adjacent screenshot times;
      demand screenshot clock difference consistent with neighbour videos.
  Missing/ambiguous -> FAIL CLOSED, do not invent guest / release PASS.
  Downstream boundary, XML, audio, Premiere and final QA remain active.

To install:
  1) Close Studio normally, do not force stop.
  2) Unpack ZIP and run INSTALL_SCENE_V4.cmd.
  3) See INSTALLED plus backup path.
  4) Reopen Studio. Reprocessing 904 must be done via GUI,
     choose reprocess preserving previous version.
  5) Do NOT overwrite existing six approved 904 XML.
  6) If needed close Studio and run ROLLBACK_SCENE_V4.cmd.

Backup: F:\RG_AUTO_EDIT\RG Auto Edit Data\RG_REPAIR_BACKUPS
Installer refuses active video processing, hash drift or running queue.
No video is processed during installation.
