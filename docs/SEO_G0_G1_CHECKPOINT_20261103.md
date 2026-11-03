# Universal SEO G0/G1 checkpoint — 2026-11-03

Plan: docs/SEO_UNIVERSAL_WORK_PLAN.md. This record is an audit, not release approval.

## G0 baseline (PARTIAL)
- AlexPC remote online, code/report files located.
- SHA256 of local QA source free_tools.py: c437b8561398095ad94e6b959a1586bbf1fd6e432e150de89d779bb04b395d00.
- SHA256 RG_VIDEO_SRT_MATCH_10.json: 5b98e873ae0d22ad37629645693b84398796cba1f9149f04b0a60e74480ba67a.
- SHA256 RG_LMSTUDIO_ONE_REAL_SRT_MEitKm687xo.json: 14d8798bd935f2c14534056f479995dbf56a81102e21d170f3c29df273203e0b.
- SHA256 RG_SEO_TEN_EDITORIAL_GATE.json: b4d3968a1287015143bd65ee9e817d88345dab53110ec7dfb655d76e180402df.
- No YouTube write attempted. Existing DB/backups must be verified before G0 acceptance; G0 remains PARTIAL.

## G1 source gate (IN DEVELOPMENT)
- Added src/rg_youtube_control/seo_source_integrity.py as an isolated offline, fail-closed component.
- New test file tests/test_seo_source_integrity.py: **10 passed in 0.02s on AlexPC** (isolated checkout).
- Tests cover multiple synthetic videos, ID mismatch, untrusted provenance, missing topic anchors, unrelated transcript, malformed timestamps, too short captions and truncation.
- 10/10 files in remote transcripts directory exist, but filename alone is NOT verified provenance.
- Actual MEitKm687xo.srt has 165 cues; when its source ID and provenance are unknown, the new validator correctly reports BLOCKED_SOURCE (unverified provenance). Original YouTube subtitle download was confirmed in previous live session, but no durable per-file manifest is currently attached to the shared transcripts root.
- Important: first implementation is NOT integrated into UI or production SEO path. It cannot by itself assert transcript-to-video semantic identity or audio correctness.
- Pending: durable original-download source manifest; verify duration and semantic correspondence for diverse videos; integrate block into SEO entrypoint; run mixed-real-video acceptance.

## G0–G6 audit
G0 PARTIAL, G1 IN DEVELOPMENT, G2–G6 NOT STARTED. No release approval. PR #168 remains experimental.

## Next action
Add source provenance manifests with ID, URL and verification evidence to acquisition pipeline, wire gate ahead of generator; repeat mixed video tests. Do not manufacture provenance from filenames.


## G1 checkpoint 2 — after three changes
- Added `seo_caption_manifest.py`: acquisition-time source URL, verified acquisition type, ISO acquisition time, duration and byte SHA-256; validation refuses absent, tampered, unknown or contradictory manifests.
- Added 8 generic manifest tests (ID mismatch, tampering, missing JSON, duration conflict, missing provenance). Combined **18/18 PASS** on AlexPC in isolated `C:\RG_YT_AGENT_RUNNER\SEO_G1_CHECK`.
- Wired NAS SRT screening in `ui.py` before loading local captions. Unverified NAS file no longer accepted merely because it is named after the video ID. Falls back to existing direct YouTube transcript routes.
- UI syntax compilation PASS. Production GUI integration and mixed-video live source retrieval NOT YET VERIFIED.
- IMPORTANT: No old manifests were fabricated for legacy captions. Acquisition pipeline still needs to write a manifest when caption bytes are actually downloaded. This is G1's remaining blocker.
- Audit after three changes: G0 PARTIAL, G1 IN DEVELOPMENT, G2–G6 NOT STARTED. No release approval or YouTube edits.

## G0 completion / G1 checkpoint 3 (2026-11-03)
- G0 PASS: AlexPC main DB read-only `PRAGMA integrity_check=ok` at `%LOCALAPPDATA%/RGYouTubeControl/rg_youtube_control.db`; SQLite backup safely created in `F:/RG_YOUTUBE_CONTROL_QA/BASELINE_20261103/rg_youtube_control.db`. Backup integrity `ok`, 10 tables, 543 rows in `optimization_drafts` in both copies, size 8,499,200 bytes, backup SHA256 `24ca219bc37e94572e3bbd3b75864cbf791ed1179e13e8bde954cf365600fc53`. Baseline code/report hashes recorded above. Recovery is file restoration only with the app closed; NOT performed.
- G1 in development: new `seo_caption_acquisition.py` records captions retrieved directly from YouTube with an acquisition-time SHA-256 manifest in a separate local cache; `ui.py` checks source before SEO generation and rejects failed preflight. Legacy NAS file without a verifiable manifest is skipped, not trusted by name. Source URL, timestamps, duration and source ID validation hardened.
- Tests executed on AlexPC using immutable Git commit b77b23e33c6f5c2948c5eae783a1aaea8d24d7fe: **30 passed in 0.26s**, modified UI Python compile PASS. An initial attempt used a stale cached branch URL and failed 4 tests; re-fetched immutable commit and corrected the source synchronization issue. Later tests passed.
- Live read-only trials from YouTube with recorded metadata: `MEitKm687xo` 593 seconds/165 cues, `pUWdQ8k6e4g` 2634 seconds/1248 cues, `GQL6N4jQpI8` 2285 seconds/1073 cues. All returned `NEEDS_REVIEW` and `TOPIC_MATCH_UNVERIFIED`, not editorial approval. Video ID and duration were used from direct YouTube retrieval, never from legacy filename.
- Known remaining G1 blockers: independent topic/audio match validation, language plausibility checks, full installed GUI smoke/integration tests; acquiring captions only by requested video ID cannot guarantee transcript accuracy. These tests do not approve an installer.
- Audit against G0–G6: **G0 PASS; G1 IN DEVELOPMENT; G2–G6 NOT STARTED.** No external YouTube metadata write. No working app replacement.


## G1 checkpoint 4 — language plausibility, heterogeneous real inputs
- Added conservative script plausibility and repeated/empty transcript signals in `seo_source_integrity.py`. Signals never serve as language identification, factual proof, or automatic editorial approval.
- Added 6 regression tests for Ukrainian/Russian mixed dialogue, English speech, sparse input, repeated captions and normal varied transcripts.
- At commit 07a1160c4f1aa4c7818407f737cfdfe855fd8117, AlexPC isolated QA: **36/36 PASS** (0.26 seconds).
- Live verification of persisted direct YouTube captions: MEitKm687xo (165 cues), pUWdQ8k6e4g (1248), GQL6N4jQpI8 (1073). All **NEEDS_REVIEW**, topic evidence **TOPIC_MATCH_UNVERIFIED**, no anomalous script or repeated-caption signals. This does NOT independently compare audio to captions.
- Checkpoint result: G0 PASS, G1 IN DEVELOPMENT, G2–G6 NOT STARTED. Remaining G1: validate real GUI workflow and independently ground content match rather than treating source ID alone as semantic proof.
- Release gate CLOSED. No installed application update or YouTube changes.


## G1 checkpoint 5 — cross-transport content corroboration (2026-11-03)
- Added `seo_caption_corroboration.py`: multiple timeline windows, cue-text agreement, distinctive-token agreement, and explicit large timestamp-drift detection. Results distinguish `CAPTION_TRANSPORTS_CORROBORATE`, `CAPTION_CONTENT_CONFLICT`, `CAPTION_TIMELINE_CONFLICT` and insufficient evidence. NEVER editorial approval.
- Regression tests `test_seo_caption_corroboration.py` include unrelated subjects, shifted captions, Cyrillic dialogue, missing counterpart and malformed inputs. Initial attempts exposed false negatives; fixed matcher before acceptance.
- Real paired retrieval: YouTube Transcript API vs independent yt-dlp SRT for MEitKm687xo: **4/4 time windows corroborated**; old mislabeled NAS SRT backup: **BLOCKED_SOURCE/CAPTION_CONTENT_CONFLICT, 0/4 windows matched**.
- Draft UI source path now calls cross-transport comparison before SEO creation. A second transcript unavailable -> NEEDS_REVIEW; explicit conflict -> block. This is an integration CODE change, not GUI runtime acceptance.
- AlexPC: **44/44 isolated unit tests PASS** and modified `ui.py` syntax compile PASS at commit a8b08b46a7926ff5f614bb99a9defad9d0b6779f. No release installation.
- Remaining G1: full GUI runtime smoke, caption translation/locale mismatch safety, mixed-video independent-content results, and runtime launch with installed app. Avoid changing published video metadata.
- Plan audit: G0 PASS, G1 IN DEVELOPMENT, G2–G6 NOT STARTED.
