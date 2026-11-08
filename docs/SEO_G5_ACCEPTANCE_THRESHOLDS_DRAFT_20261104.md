# SEO G5 acceptance thresholds — proposed, not approved

Date: 2026-11-04. Scope: RG YouTube Control, local source-grounded Ukrainian SEO only.

## Prerequisites before opening the 10-video holdout
- A source-matched, editable review set of at least 30 distinct videos.
- An independent **human** editorial verdict on source relevance, attribution, natural Ukrainian, and A/B diversity. A second LLM is risk triage, not human approval.
- Freeze generator prompt, validation code and quantitative thresholds before running the holdout.
- Back up installed application/DB; no writes to YouTube throughout QA.

## Proposed release gate
1. **Zero** source/video-ID mismatches or unsupported specific factual claims counted as editor-approved.
2. Every non-blocked candidate has one main Ukrainian title, exactly three meaningfully distinct A/B options (all <=100 characters), a 300–1400-character description, and 8–15 relevant tags.
3. Human scores >=4/5 in factual faithfulness, Ukrainian naturalness, and relevance for at least 90% of eligible items; zero critical hallucinations across every item.
4. A video with insufficient original SRT or unresolved provenance is BLOCKED_SOURCE, never silently filled in.
5. Holdout: run once on 10 locked, previously unseen videos. Report all failures; no prompt tuning on holdout.
6. No automatic metadata updates, replies or publication; only explicit editor-approved drafts may later enter publication flow.
7. Windows release: real-source QA plus install, silent-upgrade, GUI startup, DB/draft preservation, rollback and SHA256 PASS.

## Staged evidence as of 2026-11-04
- 19 of 20 real source-matched SEO candidates passed deterministic format and numeric checks in AlexPC staging; 1 SRT provisional.
- Independent Gemma (separate from Qwen generator): 17 candidates flagged for review, 10 medium risk and 7 high risk. No semantic sign-off from these labels.
- 10 locked holdout SRT hashes re-checked, 10/10 match; holdout SEO and human ratings not run.
- Local offline test suite previously 179/179 PASS; release build and real production-account GUI upgrade still not certified.
- No publication, no YouTube writes. **Final release remains BLOCKED pending human acceptance and independent holdout.**
