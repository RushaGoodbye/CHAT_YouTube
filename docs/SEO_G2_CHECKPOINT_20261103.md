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
