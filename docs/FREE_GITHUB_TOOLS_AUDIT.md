# Free GitHub Tools Audit - RG YouTube Control, 2026-10-08

## Non-negotiable rules

No paid APIs, no trials, no credits/keys, no new YouTube Data API cost for public reads. Never touch thumbnails, livestream settings, replies, likes, or moderation-pending comments. Never use the public scraper as an authenticated moderation API. Reuse the existing Windows PySide6 app, Ollama and NAS transcripts; keep the installed 0.7.6 untouched until tests pass.

## Repositories assessed

| GitHub repository | License | Decision | Reason |
| --- | --- | --- | --- |
| yt-dlp/yt-dlp | Unlicense for source wheel; standalone binaries can have GPL components | Keep existing | Public metadata / captions. Unofficial access can break. |
| jdepoix/youtube-transcript-api | MIT | Keep existing | Captions without YouTube Data API; NAS fallback already present. |
| ollama/ollama | MIT | Keep existing | Local qwen3:8b. Generated facts need transcript review. |
| rapidfuzz/RapidFuzz | MIT | Integrate | Near-duplicate YouTube tags, retain distinct topical terms. |
| egbertbouman/youtube-comment-downloader | MIT | Integrate read-only | Export max 100 recent publicly visible comments to CSV, API 0, not a moderation/reply tool. |
| SYSTRAN/faster-whisper | MIT | Defer | Existing Auto Edit / NAS Whisper pipeline covers transcription, avoids duplicate GPU runtime. |
| ggerganov/whisper.cpp | MIT | Defer | Model download/runtime testing required. |
| MaartenGr/KeyBERT | MIT | Defer | Torch / sentence-transformers too heavy for desktop installer. |
| INESCTEC/yake | LGPLv3 (metadata/classifier mismatch) | Defer | Legal redistribution review and many dependencies. |
| csurfer/rake-nltk | MIT | Defer | NLTK language corpora and extra language verification required. |
| sdil87/trendspy | MIT | Defer | pandas/numpy, unofficial Google endpoints; existing trends data is consumed already. |
| flack0x/trendspyg | MIT | Evaluate RSS-only later | Chrome required for some flows, upstream unstable. |
| SkyBotsDeveloper/youtube-search-python | MIT | Reject production | Unstable internal YouTube client endpoints. |
| boudinfl/pke | GPL-3.0 | Reject bundled use | Copyleft and complex NLP dependencies. |
| ChocoData-com/youtube-suggest-scraper | API key and one-time credits | Reject | Not fully free/unrestricted for user intent. |

## Changes in branch feature/free-open-source-seo-v1

- RapidFuzz integrated into existing package tag normalization, which is reused by optimization draft validation/editing; strong threshold 97 and equal word-count safeguard to preserve distinct words. The 500-character and 15-tag limits remain.
- Public-comment sample reader integrated into Optimization -> Додатково -> Публічні коментарі (0 API, CSV). Only reads public comments, exports to Downloads; does not touch SQLite moderation, likes, approval, replies, or YouTube metadata.
- Dependencies declared for Windows CI and Python packaging, tests mock the public reader with no live network access.
- A pull request must pass test suite and Windows installer build before any merge or release.
- Public comment data and Trends are NOT accepted as factual evidence about video dialogue; transcript remains the ground truth. All scrapers may be rate-limited/blocked even when YouTube API quota is zero.

## Follow-up after tests

Use NAS SRT first and existing transcript fetch fallback. Investigate Google Trends RSS without Chrome separately; do not bundle large NLP libraries until measurable benefit. No unattended publishing of altered descriptions.

Sources: https://github.com/yt-dlp/yt-dlp ; https://github.com/jdepoix/youtube-transcript-api ; https://github.com/rapidfuzz/RapidFuzz ; https://github.com/egbertbouman/youtube-comment-downloader ; https://github.com/INESCTEC/yake ; https://github.com/MaartenGr/KeyBERT ; https://github.com/flack0x/trendspyg .
