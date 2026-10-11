# RG YouTube Control 0.7.20 - complete draft diagnostics

Fixes the user-confirmed issue in 0.7.19: clicking «Перевірити пакет» on a draft returned only «Пакет не має статусу готовності» and hid known A/B title repetition.

- The editorial gate now collects all reasons, including draft status, lack of approval, missing A/B titles and repeated plot angles. Publication stays blocked unless every requirement is met.
- The editor shows an actionable Ukrainian message for same-story A/B titles, while retaining valid Russian search-language headlines and Ukrainian descriptions.
- Scheduled streams and safe metadata-only packages remain exempt from the three A/B title requirement, preserving existing behavior.
- Existing SEO drafts are not overwritten, thumbnails are untouched and no YouTube API writes are performed.
- Added tests using the real Shoigu package and the actual draft status from the operator's screen.
