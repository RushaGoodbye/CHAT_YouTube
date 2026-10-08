# RG YouTube Control 0.7.4

Stabilization release after 0.7.3.

- End-to-end SEO package normalization before validation and save.
- Deduplicated YouTube tags with 15-tag and 500-character limits.
- Exactly three relevant hashtags are normalized automatically and no longer block the package.
- Scheduled streams treat chapters as optional.
- Scheduled stream audits no longer report missing chapters as a package problem.
- A/B title variants remain advisory unless they violate YouTube title limits.
- Package application strips timing lines from descriptions.
- Regression coverage added for package normalization and scheduled-stream validation.
