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
