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
