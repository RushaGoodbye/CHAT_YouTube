# RG YouTube Control 0.7.24 - full video SEO evidence and protected drafts

- Analyze every available transcript segment and keep the grounded topics across the complete timeline, not a two-topic cutoff. A full topic map is retained separately from the short YouTube synopsis.
- Align chapters to actual caption timestamps instead of inventing fixed chapter times. Guard against repetitive and unsupported chapter labels.
- Correct recognizable ASR mistakes in displayed topics (e.g., Шагу → Шойгу from known video title) and awkward language in Ukrainian SEO descriptions.
- Strengthen A/B editorial recovery and checks. Three candidate Russian titles must not repeat one story, introduce unsupported outcomes or degrade into unreadable raw ASR quotes. Two-block videos can still recover multiple different quote-based *review-only* ideas.
- Compare against any existing saved SEO draft rather than treating a blank live YouTube description as the only starting point. Preserve existing seven-chapter draft when a new candidate is less complete; save risky proposals separately for review.
- Preserve current title rather than replacing it with a shorter equivalent merely to change punctuation. Do not automatically publish or edit thumbnails.
- Read-only real-video QA on AlexPC checks Shoigu (9:53, 165 caption rows, six source-grounded topics), complete topical coverage, quote-backed chapters, A/B quality, project links and exactly 3 hashtags. Windows full-test and installer smoke tests required for release.

No bulk YouTube API writes or automatic editorial approvals.