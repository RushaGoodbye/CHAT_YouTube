# RG YouTube Control 0.7.8 - local SEO stabilization

Release following the observed "missing title" failure on 0.7.7.

- If local Ollama omits the new title, use the already published title as a safe fallback instead of aborting the entire package.
- Support additional model title field names and recover line-separated A/B suggestions without splitting text into characters.
- If A/B suggestions are incomplete, retain the content as a review-only draft. Never silently mark it ready to publish.
- If there is no transcript, do not assign automatically ready status because generated text cannot be verified against dialogue.
- Avoid a redundant Ollama description-recovery request when the first draft is already valid.
- Show "Локальний SEO вибраного" in the normal Optimization menu without requiring advanced diagnostic mode.
- Preserve source title, original description, tags, moderation state, thumbnails and publication settings.
- Preparing and reviewing metadata consumes 0 YouTube Data API quota. No YouTube changes are made before explicit application.

QA: PR #83 completed a clean Windows Build with 280 passing tests; the release is rebuilt from main and verified separately.
