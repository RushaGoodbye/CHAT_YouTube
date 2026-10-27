# Read-only audit of archived dialogue SEO drafts (2026-10-13)

This is an editorial audit, **not** a publication or import authorization.

Input: local archived file `RG_SEO_READONLY_V11/READONLY_PREVIEW.csv` (48 dialogue drafts), not the live Windows database.

## Reproduced observations

- 48 rows, all `HOLD_REVIEW`.
- Every description (48/48) contains the boilerplate sentence `Обговорюємо аргументи учасників`.
- 44 distinct leading description blocks (split before donation links), but the shared boilerplate still makes the drafts weak for editorial publication.
- The IDs (e.g. `886_2`) are dialogue identifiers, **not** 11-character YouTube video IDs; no verified dialogue-to-published-video mapping is provided by this CSV.

## Release blockers

1. Do not apply these 48 drafts to any YouTube video based on stream/dialogue numbering or fuzzy title similarity.
2. Replace boilerplate with **specific transcript-grounded** summaries while retaining important verified topics.
3. Verify primary and three A/B/C titles separately against transcript evidence; avoid quote substring false matches.
4. Require editorial review of real output on both main and LIVE channels.
5. Do not change thumbnails or published YouTube metadata in this QA process.

## Acceptance criteria for an actual SEO rollout

- Confirm video ID <-> source evidence mapping for each targeted item.
- Export a side-by-side before/after review per confirmed item.
- Explicitly separate `HOLD_REVIEW`, `READY_FOR_EDITOR` and human-approved publication states.
- Report actual verified count, not merely a success count from generator unit tests.
- Keep all operations read-only until explicit approval.
