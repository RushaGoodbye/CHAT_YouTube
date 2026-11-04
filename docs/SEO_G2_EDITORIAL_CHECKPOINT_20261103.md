# G2 editorial acceptance checkpoint — 2026-11-03

Master plan: docs/SEO_UNIVERSAL_WORK_PLAN.md; issue #169. Development PR #171.

## Completed in this batch
- Created `seo_editorial_acceptance.py`: reusable review packet from evidence records with the original quote, its ±30 second transcript context, model topic/summary and blank human ratings. Human review fields cannot be filled from source-integrity PASS.
- Created a risk-only critique adapter. It validates risk labels, converts critic errors into HIGH risk, and forces `editorial_approved=false` / `publication_allowed=false`. It refuses to call a critic using the same model identifier as the generator.
- Added 6 regression tests in `tests/test_seo_editorial_acceptance.py`: source context, missing coverage, wrong ID, risk flag, critic failure, anti-auto-approval, plus separate-model enforcement (6 tests).
- Added a dedicated GitHub Actions workflow `.github/workflows/seo-g2-editorial-qa.yml` to run source, recovery and editorial tests on pull requests.

## Limitations and current gate
- AlexPC command execution through Remote Desktop Commander is currently blocked by the tool environment. The new test module and workflow are committed, but **not executed or marked PASS**. GitHub returned no workflow run for commit 051e8fb39609f5a8af60ef5f1df319e38eab502d.
- Previous verified baseline **79/79 PASS** applies only to the earlier G1/G2 source and recovery code; it must NOT be counted as a test result for this new editorial module.
- No human editor has scored topic fidelity, attribution, unsupported details, context omissions or natural Ukrainian. A second local model critique is NOT a substitute for human editorial labels.
- No installed app changes, no YouTube writes, no publication allowed.

## Next actions
1. Execute new test suite on AlexPC or GitHub CI and fix defects.
2. Create review packets for 30–50 diverse verified video sources; reserve at least 10 videos untouched for final acceptance.
3. Run a distinct critic model to prioritize questionable items, then collect human ratings and define acceptance threshold before final holdout.
4. Only close G2 with documented manual accuracy, coverage, error categories, and rollback conditions.

Plan audit: G0 PASS; G1 staging PASS; G2 technical source-evidence PASS on 3 examples, editorial review **NOT ACCEPTED**; G3–G6 NOT STARTED.


## Recovery verification after Runner restart (2026-11-03)
- AlexPC remote execution is functioning again. Self-hosted YouTube runner is online: `C:/RG_YT_AGENT_RUNNER/actions-runner/bin/Runner.Listener.exe` (PID 19544). Local LM Studio server running on port 1234 with `rg-gemma4-12b` loaded.
- Synced editorial acceptance module and tests to isolated AlexPC staging. **85/85 G1+G2 tests PASS** in 2.11 seconds. This specifically supersedes the previous checkpoint's 'new tests unverified' issue.
- Exported 23 editor review items from the three real source-grounded video records: `MEitKm687xo` 3, `pUWdQ8k6e4g` 10, `GQL6N4jQpI8` 10. Files stay locally on AlexPC under `C:/RG_YT_AGENT_RUNNER/SEO_G1_CHECK/g2_editorial_review/<video_id>.editorial.json`. Each includes original quote, local SRT context, topic and summary, empty human scores. All editorial_approved=false, publication_allowed=false.
- G2 editorial correctness is NOT yet accepted; 23 cards exist but no human editorial labels have been entered. Second-model review not yet run. Next stage: independent critic and human-scored representative set; G3–G6 remain closed.


## Verified AlexPC independent-model risk scan, same day
- Restored AlexPC command access. `Runner.Listener.exe` PID 19544 on the expected `C:/RG_YT_AGENT_RUNNER/actions-runner` path. `rg-gemma4-12b` LM Studio generation model was unloaded and distinct `rg-qwen3-14b` loaded for critique on local server port 1234.
- Actual combined G1+G2 QA: **85/85 PASS** on AlexPC. This includes the new editorial review/critic regression tests.
- Exported 23 reviewer cards from three independently checked source SRTs into `C:/RG_YT_AGENT_RUNNER/SEO_G1_CHECK/g2_editorial_review` (3 + 10 + 10 cards). Human score fields blank.
- Executed distinct-model `independent_llm_critique` on all 23 cards, locally and read-only. Qwen risk-only distribution:
  - `MEitKm687xo`: 2 low, 1 medium, 0 high.
  - `pUWdQ8k6e4g`: 6 low, 2 medium, 2 high.
  - `GQL6N4jQpI8`: 6 low, 3 medium, 1 high.
  - Overall **14 low / 6 medium / 3 high**. Each JSON critique stored beside its corresponding editorial card as `<video_id>.critic.json`. No item was approved, and no publication flag changed.
- An AI reviewer, even a separate model, is NOT a human editorial score. **G2 editor sign-off is still missing**. Investigate 9 medium/high items first, then sample low-risk items. Do not promote G3 or approve installer based on this risk scan.
- No installed app changes, YouTube metadata changes or publications.


## G2 checkpoint 5 — risk review triage on real contested cases
- Reviewed all **9 medium/high Qwen review cards** with their original verbatim quote, local source context, candidate topic/summary and critic objections. Found common failure categories: unsupported geographic specificity, name transcription mismatch, invented causes/motives, excessive generalization, insufficient qualification, and missing dialogue context. Some critic complaints contradict the quoted speech; risk flags are **unverified reviewer suggestions**, not editorial facts.
- New universal module `seo_editorial_triage.py` assembles a per-video decision queue prioritizing high then medium then low, preserving context and all critic objections. It rejects incomplete or duplicate critic results and wrong video IDs. Does NOT approve any item, change topics, or publish anything.
- Generated 3 read-only triage reports and one consolidated `G2_PRIORITY_REVIEW_9.json` on AlexPC under `C:/RG_YT_AGENT_RUNNER/SEO_G1_CHECK/g2_editorial_review` (MEit 1 priority, pUW 4, GQL 4). The queue is review-ready, all decisions unset.
- Added 5 triage regression tests and included them in dedicated CI workflow. **90/90 combined G1+G2 tests PASS** on AlexPC in 1.59 s.
- Control: G0 PASS; G1 STAGING PASS; G2 evidence and technical regression PASS but human subject-fidelity review remains **NOT ACCEPTED**, G3–G6 not started. No changes to installed app or YouTube.


## G2 checkpoint 6 — source-centered context + constrained editorial revision (2026-11-03)
- Inspected nine disputed medium/high-risk items. Categories observed: wrong name recognition (e.g. Шойгу), unsupported geographical specificity, unsupported dates/causes, overly broad generalization, context loss; some independent critic claims contradict literal source dialogue. Never infer editor acceptance from critic labels.
- Added `seo_editorial_revision.py`: a single read-only, Ukrainian-language reformulation proposal conditioned on the original quote, local transcript context and *untrusted* critic objections. Fails closed on missing quote/context, malformed output, invalid lengths and novel numeric details. Always `editorial_approved=false`, `publication_allowed=false`. No specific video exceptions.
- First live Qwen3-14B revision run of nine priority items: 4 REVIEW_REQUIRED, 5 BLOCKED_SOURCE_CONTEXT. Root cause: `build_editorial_review_packet` truncated the first 2500 characters of a long context, cutting out the actual quote even though it had been verified in SRT.
- Fixed `build_editorial_review_packet` to center its context window around the actual source quote (retaining fallback context for multi-cue ASR), with regression test.
- Rebuilt all 23 real review packets and nine-item priority queue. Second live Qwen revision batch: **7 REVIEW_REQUIRED**, **1 BLOCKED_REPAIR_FAILURE**, **1 BLOCKED_UNSUPPORTED_NUMBER**. Two remain blocked. Stored in `C:/RG_YT_AGENT_RUNNER/SEO_G1_CHECK/g2_editorial_review/G2_NINE_REVISION_PROPOSALS.json`.
- Independently checked all seven Qwen revision proposals with distinct loaded Gemma-4-12B. Risk-only critic labels **7 low**, no auto-approvals. These seven were not promoted into published metadata and require human content checks. Stored in `G2_REVISION_SECOND_MODEL_REVIEW.json` beside the original SRT reviewer cards.
- **96/96 combined G1+G2 tests PASS** on AlexPC (1.60 seconds), including five new revision tests and source-centered context regression. GitHub workflow updated to cover revision.
- G2 editorial acceptance STILL OPEN: no verified human scoring, two blocked proposals, and human reference set of 30–50 diverse videos plus 10 holdout not completed. G3–G6 NOT STARTED. No installed app changes, YouTube mutations or publication.


## G2 checkpoint 7 — bounded repair retry corrected and verified
- Fixed an accidental stale exception handler left after editing `seo_editorial_revision.py` (commit `573f302`). Added exactly one corrective model retry for malformed JSON, invalid title/summary lengths, or ungrounded numeric claims. No content is accepted from a failed attempt.
- Initial live AlexPC regression exposed an over-escaped regex that failed to recognize novel numbers. Corrected it (commit `a0a8a5f`). Confirmed two new regression cases: invalid JSON recovers on second attempt, and generated number 999 is removed instead of being accepted.
- All **98/98 staged G1+G2 tests PASS on AlexPC** (1.58 seconds), including the retry tests. The original installed application and YouTube were not changed.
- **Important distinction:** test PASS is not G2 editorial acceptance. The two historically blocked live-model cards have not yet passed a fresh real-model retry; continue recording them as unresolved until a successful new live test demonstrates otherwise.


## G2 checkpoint 8 — fix stale handler, live rerun blocked by local model latency
- Corrected syntax-invalid stale handler and rewrote the bounded second model attempt in `seo_editorial_revision.py`. Added two new regression tests covering successful retry after malformed JSON and rejection/revision of ungrounded number 999. Initially uncovered an overescaped numeric-regex defect; fixed it before sign-off. Commits: `573f302`, `3665856`, `a0a8a5f`.
- **98/98 combined G1+G2 isolated tests PASS on AlexPC** (1.58s). No installer or YouTube changes.
- Reloaded the local Qwen3-14B inference model and attempted a real all-nine rerun. Local LM Studio inference became extremely slow; first item returned `BLOCKED_REPAIR_FAILURE` after timeout/retry. The targeted read-only test session PID 34332 was terminated without changing installed app or YouTube. No new real-model acceptance result was obtained for the other items. Previous seven review proposals and two blocked cases remain the last completed baseline, and all are still unapproved.
- G2 editorial acceptance remains **BLOCKED** until reliable model execution and human semantic ratings are documented. The tests verify code behavior, not the truth of individual SEO claims.


## G2 checkpoint 9 — 2026-11-04, targeted replay of the last two blocks
- AlexPC remote connected. LM Studio server had stopped and models were unloaded after previous session; restarted the server and loaded `rg-qwen3-14b`. Two-item replay only, without recomputing other videos.
- Discovered source of `pUWdQ8k6e4g` card 8 failure: the original revision prompt repeated an old disputed topic/summary and critic objections; Qwen returned an empty JSON object twice. A short source-centered, original-quote-only prompt returned a usable Ukrainian topic/summary. Generic retry now removes earlier model and critic claims from the request. New regression checks that the second request carries no contaminated topic. The original transcript explicitly mentions Tyumen, a fuel discussion, and use of a bicycle: parts of the previous critic's high-risk assertions were false positives.
- `GQL6N4jQpI8` card 3 was blocked because gasoline grade numbers were spoken in SRT as ordinals ("сотый, девяносто пятый, девяносто второй"), while the draft wrote digits. Added generic RU/UK spoken-number recognition, guarding against invented 999. Corrected compound parsing so ninety-fifth only licenses 95, not standalone 90 or 5. A separate 90 occurs elsewhere in the review context; numerical support is context-sensitive and does not establish external truth.
- Two targeted live-model cards in `C:/RG_YT_AGENT_RUNNER/SEO_G1_CHECK/g2_editorial_review/G2_TWO_BLOCKED_RECHECK_20261104.json` now both return **REVIEW_REQUIRED** with original quotations unchanged and `editorial_approved=false`, `publication_allowed=false`. This resolves the model-output blockers, NOT editorial human acceptance.
- Combined **106/106 G1+G2 staged tests PASS** on AlexPC. Separate isolated Qt smoke: 9 tabs constructed, clean cleanup PASS. Updated CI workflow to cover spoken numeric tests.
- Existing model-created editorial suggestions still require independent editorial sign-off; there is no measured 30–50-video human-rated acceptance set or 10-video holdout. G2 editorial approval BLOCKED; G3–G6 not approved, no installer changes and no YouTube writes.
