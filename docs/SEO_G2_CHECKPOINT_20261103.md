# G2 universal evidence checkpoint — 2026-11-03

Parent: G1 source integrity branch / draft PR #170. Master plan: docs/SEO_UNIVERSAL_WORK_PLAN.md.

## Gate transition
- G0 PASS, G1 STAGING PASS (51/51 source tests; 9-tab offscreen Qt MainWindow startup and full SEO-path mock integration). Never claim that two YouTube caption transports independently verify original audio.
- G2 IN DEVELOPMENT. Existing `dialogue_seo.analyze_all_timeline_blocks` already chunks and validates exact quotations but does not bind model summaries to exact caption timestamps or explicitly label their factual truth status.

## Changes
- Added `seo_evidence_records.build_evidence_records`, a generic evidence-record conversion layer. Captures video ID, topic, unchanged quote, source start/end, caption-vs-block timestamp precision, type (question or attributed speech), and explicitly `factual_truth_verified=False`.
- Quotes absent from the original captions are rejected. Quotes spanning adjacent captions are accepted only when reconstructed from rows inside the timestamped analysis block and marked with coarse block timestamp precision.
- No hard-coded names, officials, institutions, news events or topic-specific SEO.
- 7/7 G2 synthetic tests PASS on AlexPC in isolated staging, covering two unrelated subjects, unsupported statements, questions, multi-cue quotations and unverified blocks.
- G2 has NOT been connected to the live SEO generator, no real-video evidence coverage/claim typing acceptance has occurred. This is not release approval.

## Next actions
1. Integrate evidence records with existing full-transcript analysis, preserving all blocks.
2. Add explicit claim/attribution taxonomy (opinion, allegation, observation, question) without treating utterances as facts.
3. Run mixed-topic real-SRT coverage and record failures. Keep release gate closed.

Controls: No installed application update. No YouTube writes. Avoid per-video patches. Audit again after three changes or at gate exit.


## G2 checkpoint 2 — full-SRT evidence wired into staging (2026-11-03)
- Integrated `build_evidence_records` into the actual `MainWindow._generate_local_seo_result` full-transcript branch, before `generate_seo_package_local`. Source records are embedded in the existing evidence report, preserving blocks/coverage. If no grounded records survive, draft generation is refused.
- Fixed cross-block evidence bug: an identical quote occurring elsewhere in the video is NOT attributed to the current timeline block. Quotes are now checked against original timestamped caption rows, never against invented model block text.
- Added conservative utterance labels: question / opinion / allegation / attributed_speech. `factual_truth_verified=False` for all items. This labels speech, not truth.
- Tests: **14/14** evidence-schema cases, **3/3** new actual GUI method integration tests (grounded passage passes to draft; hallucinated claim and wrong-window quote rejected before generation), combined **68/68 G1+G2 isolated tests PASS on AlexPC** (1.46s).
- Real three-video source validation with deterministic source quotations, **not AI-editorial acceptance**: MEitKm687xo 165 cues => 4/4 timeline blocks with accurately sourced quotes; pUWdQ8k6e4g 1248 cues => 15/15; GQL6N4jQpI8 1073 cues => 13/13. Zero rejected source quotes in this controlled extraction. It demonstrates timestamp/caption plumbing only, not the AI's topic correctness.
- No release install, no YouTube writes. This is staged code on feature branch, not final G2. Need real multi-video LM Studio inference, evaluate attribution and coverage, and verify fallback for partially unverified blocks before G2 acceptance.
- Plan audit: **G0 PASS; G1 STAGING PASS; G2 IN DEVELOPMENT; G3–G6 NOT STARTED.** No video-specific exception introduced.


## G2 checkpoint 3 — ACTUAL LM Studio inference / generalized coverage gate
- AlexPC LM Studio started with `lms server start`; `rg-gemma4-12b` loaded locally. An initial API trial returned HTTP 400 because LM Studio requires `response_format.type=json_schema`, not `json_object`. Corrected caller; no Ollama used.
- Full-caption, multi-block live-model trials on three distinct real video IDs using `analyze_all_timeline_blocks` (complete captions, 390 s / 4400 char maximum windows) and `build_evidence_records`: `MEitKm687xo` 165 cues, 2/2 source-grounded blocks, 3 accepted quotes, 0 rejected; `pUWdQ8k6e4g` 1248 cues, 8/9 grounded blocks, 9 quotes accepted, 1 rejected; `GQL6N4jQpI8` 1073 cues, 5/8 grounded blocks, 7 quotes accepted, 4 rejected. Totals: 19 blocks processed, **15/19 blocks grounded**; 19 accepted quotes, 5 rejected; 4 blocks without accepted evidence: pUW block 8, GQL blocks 2,5,6. Times ~14.4/82.6/57.7 seconds. All review-only, publication_allowed false.
- Important defect identified: the model's own `blocks_with_evidence` said 19/19 even when 4 blocks lacked source-verified quotes. Fixed `build_evidence_records` to report `blocks_without_grounded_quotes` and `complete_evidence_coverage`; full-SRT UI generation now refuses a draft if any analyzed block has no surviving quote. No video-specific rules. Exact rejection reasons: 5 x `QUOTE_NOT_IN_SOURCE`.
- Tested source coverage and missing-block fail-closed behavior on AlexPC: **70/70 G1+G2 staged regression tests PASS** (1.43s), including mock GUI-path tests where partial grounding blocks SEO.
- Editorial subject relevance, claim correctness, and true audio correspondence are NOT proven by this test. G2 remains **IN DEVELOPMENT / acceptance BLOCKED**: current live-model evidence coverage is only 15/19 blocks, below full-coverage gate.
- Next corrective action: generic bounded recovery of ungrounded blocks using original source quotes / independent review. Do not approve G2, G3 or production installer until diverse representative trials pass. No installed app modification or YouTube writes.
