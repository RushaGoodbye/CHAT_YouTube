# RG YouTube Control 0.7.9 - Complete transcript SEO evidence engine

User-requested improvement after SEO preview lost most dialogue themes.

- Read the complete accessible subtitle/transcript timeline from NAS SRT or public YouTube captions. Analyze every timestamped cue, rather than only a 12,000-character summary.
- Split into bounded chronological windows (not asserted speaker/dialogue boundaries) and extract up to three anchored themes per window through local Ollama.
- Validate every proposed evidence quote against the corresponding source text, allowing punctuation differences but no invented source words.
- Cache verified evidence per window for efficient resume; save a full chronological theme audit under app data / seo_evidence / VIDEO_ID.json.
- Create Ukrainian SEO descriptions from the all-window topic map; append distinct grounded subjects omitted by the first draft where space permits.
- Never silently delete important subjects to fit a description. Missing/unverified topics stay in the evidence report; unsafe packages require review or are blocked.
- Generate three Russian A/B title angles. Detect near-duplicate hooks, short/long titles and ungrounded topic words; retry weak sets once.
- Show analyzed/evidence-backed window counts and topic list inside the before/after preview. Show local processing stages and current N/M block progress.
- Keep generated semantic SEO review-only before an explicit user decision. No automatic changes to YouTube or thumbnails, publication dates, visibility, pending moderation, replies or likes. Reading public metadata/transcripts and local analysis uses no YouTube Data API quota.

Notes:
- If a video lacks usable captions, the app cannot truthfully analyze its dialogues. Use a complete NAS SRT first.
- Existing auto-subtitles may contain ASR errors; a confirmed quote only establishes a source transcript match, not objective factual correctness.
- On long videos, local Ollama processes multiple blocks. First pass can take time; repeat passes reuse the cache.
- 289 automated tests passed in PR #84; real-model transcript quality must still be confirmed on a representative video before processing the full archive.

PR: https://github.com/RushaGoodbye/CHAT_YouTube/pull/84
