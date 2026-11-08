# G2 real-video validation cohort — 2026-11-04

Development PR #171; acceptance issue #169.

## Source acquisition and locked partition

- AlexPC connected, application database opened strictly read-only to select candidate video IDs and published durations.
- Retrieved **37 new captions directly from YouTube**, requesting each exact video ID via `youtube_transcript_api`; each response was stored as a timed SRT accompanied by an exact-byte SHA-256 and a source-acquisition manifest validated by `audit_caption_file`.
- The YouTube source stopped accepting additional requests with `IpBlocked`. Further remote transcript attempts were stopped; no evasion or hidden acquisition.
- Combined those 37 newly verified sources with **3 independently verified earlier SRTs** (MEitKm687xo, pUWdQ8k6e4g, GQL6N4jQpI8) without modifying their provenance records. Total **40/40 source audits passed**; exclusions 0.
- Created a deterministic lock: **30 main editorial-review videos; 10 unseen holdout videos**, protected against previous-development ID contamination. Source IDs and SHA hashes are persisted in `C:/RG_YT_AGENT_RUNNER/SEO_G1_CHECK/g2_cohort_20261104/G2_COHORT_LOCK_30_REVIEW_10_HOLDOUT.json`.
- Both source selection and quality reporting fail closed when verified sources are missing, duplicates exist, or a holdout ID enters development evaluation. No videos were used as artificial stand-ins.

## Quality evaluation gate

- The development review pipeline runs local Gemma-4-12B against **complete source SRTs**, never against title/description guesses. It writes source-grounded evidence and human-review packets to an isolated staging directory.
- Exact-quote grounding is necessary but insufficient for editorial acceptance. Model-generated topics may still misinterpret speakers, context, questions, irony and factual truth.
- `seo_g2_quality_report.py` tracks source coverage separately from independent editorial scoring. It never sets `editorial_accuracy_accepted`, `g2_accepted` or `publication_allowed` automatically.
- The 10-video holdout remains sealed until G2 editorial rules are frozen. No unverified completion claim is allowed.

## Technical tests and release boundary

- New tests for strict cohort lock and anti-holdout contamination were added to the dedicated GitHub CI workflow.
- No installed RG YouTube Control change, application-DB write, YouTube update or publication was performed.

Editorial human ratings and final holdout acceptance remain pending.
