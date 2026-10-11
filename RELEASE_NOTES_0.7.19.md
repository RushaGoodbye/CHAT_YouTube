# RG YouTube Control 0.7.19 — SEO editorial readiness

- A/B variants that repeatedly paraphrase the same event (for example, «увольнение Шойгу» versus «Шойгу уволен») are flagged for human review, even when inflected words differ.
- «Перевірити пакет» now reports editorial/A/B readiness alongside technical validation, rather than silently suggesting a technical pass is enough.
- The editor shows the effective «Чернетка» status for a stored package that fails editorial readiness, without silently modifying or deleting its database record.
- Russian-language titles and Ukrainian-language descriptions remain supported as in 0.7.18.
- Added regression tests based on the real on-screen 0.7.18 Shoigu SEO package, plus GUI tests.

This update does not automatically publish videos or modify previously saved SEO drafts. Review generated titles against actual dialogue/transcript before approving publication.
