# RG YouTube Control — SEO UNIVERSAL GENERATOR: BINDING WORK PLAN
Version: 1.0 | Adopted: 2026-11-03 | Status: ACTIVE
Owner: RG YouTube Control project. Applies to every SEO change and release.

## Non-negotiable goal
Build one reliable SEO processing system for all accessible YouTube videos, not video-specific prompt tuning. Generate Ukrainian main title, exactly 3 distinct evidence-based A/B titles, description, and relevant tags; fail closed when source evidence is insufficient. No automatic YouTube publication.

## Mandatory work sequence and gates
### G0. Freeze and baseline
- Preserve working app, DB, drafts, and backups. Do not alter YouTube metadata.
- Document baseline versions, existing failures and original examples.
- Avoid patches keyed to specific video IDs, names, offices or events.
Exit: reproducible baseline and rollback path.

### G1. Source integrity
- Load YouTube ID, verified public metadata, original/auto captions, language, duration, and provenance.
- Validate correspondence of ID, title, content, timestamps, language and transcript completeness.
- Recover correct captions where possible; otherwise BLOCKED_SOURCE and never fabricate SEO.
Exit: cross-video fixture tests including mismatched and low-quality SRT.

### G2. Universal content analysis
- Process complete long transcripts via bounded chunks and aggregation.
- Extract ranked subjects, named entities, verifiable claims, timestamps and supporting quotes.
- Separate statement, question, allegation and opinion. Track uncertainty and conflicts.
- No hard-coded rules targeting named individual videos.
Exit: documented normalized evidence schema with coverage tests.

### G3. SEO generation
- Produce Ukrainian main title, 3 meaningfully different grounded A/B angles, concise substantive description, and 8–15 relevant non-duplicate tags.
- Source-backed proposals, not generic boilerplate; no unverified names, offices, dates, counts, or claims.
- Support short, long, multi-topic, political and non-political videos.
Exit: schema, language and relevance tests on diverse inputs.

### G4. Independent validation and bounded revision
- Deterministic checks: source/ID, format, Ukrainian language, duplicates, evidence citations, unsupported specifics and A/B semantic diversity.
- Separate critic from generator; critic does not automatically authorize publication.
- One or two bounded revision passes; if defects remain, mark NEEDS_REVIEW or BLOCKED with specific reasons.
- A technical FORMAT_PASS must never be interpreted as EDITORIAL_PASS.
Exit: reproducible metrics and defect reporting for every output.

### G5. Representative acceptance corpus
- Assemble 30–50 genuinely different verified videos including short and long dialogue, multiple topics, poor captions, and non-political examples.
- At least 10 previously held-out videos for final acceptance, not prompt tuning.
- Record per-video source match, fact accuracy, Ukrainian quality, A/B distinctness, description and tags; human review provides reference labels.
- Define and agree acceptance thresholds BEFORE running final holdout. Never claim 100% universal accuracy.
Exit: consolidated acceptance report; no release if critical hallucinations or source mismatches escape gating.

### G6. Windows integration/release
- Integrate into RG YouTube Control, retain DB/drafts, backup and rollback.
- Run unit, integration, local model, offline, GUI startup and 10-video acceptance tests.
- Provide one installer only after actual passes, not merely successful CI compilation.
- No YouTube changes until separately explicitly approved.
Exit: reproducible Windows build and validated production workflow.

## Mandatory anti-regression discipline
1. Before any task or patch: state which gate it advances and the evidence of need.
2. After every change: test generalized behavior on several diverse cases, not solely MEitKm687xo.
3. Every 3 changes or at the end of each gate: audit progress against G0–G6, record PASS/FAIL/BLOCKED, deviations, and next corrective action.
4. Never replace source evidence with model confidence. Fail closed on contradictory/missing transcripts.
5. No silent switching to per-video special cases, no new tests that merely assert one hard-coded title, no one-off bypasses.
6. Keep user updates compact: completed action, measured result, remaining blocker. Never announce completion without evidence.
7. Existing PR #168 is experimental, NOT a release sign-off. Previously encountered MEitKm687xo caption mismatch and false Duma claim become generic regression cases, not production-specific exceptions.
8. Do not run continuous/background work unless an explicit automation or runner job is actually scheduled; audits occur during active work/checkpoints.

## Progress ledger
2026-11-03: Plan fixed. G0 through G6 NOT YET ACCEPTED. Next: baseline and generalized source integrity, then evidence schema. CI green alone is insufficient.
