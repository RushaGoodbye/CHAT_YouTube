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
