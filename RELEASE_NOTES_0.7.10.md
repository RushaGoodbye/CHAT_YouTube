# RG YouTube Control 0.7.10 - no-cookies local SEO fallback

Fixed the screenshot-confirmed crash in 0.7.9:
`ERROR: [youtube] Sign in to confirm you're not a bot`.

- Local SEO uses existing channel SQLite metadata (original title, description and tags) before optional public yt-dlp scraping.
- Source description is recovered from `optimization_drafts.source_description` and the latest `metadata_history`, never from a newly generated AI draft.
- Full transcript preference: existing NAS SRT -> youtube-transcript-api -> best-effort public caption track, with graceful handling if yt-dlp triggers an authentication or bot challenge.
- No export of YouTube browser cookies and no request for user's browser credentials.
- If both NAS and public subtitles are unavailable, show an actionable message describing the expected `VIDEO_ID.srt` instead of silently guessing the dialogue.
- Metadata source is marked `sqlite-cache` instead of being misrepresented as fresh yt-dlp data. YouTube Data API cost remains 0 for local preparation.
- Published metadata, channel permissions, thumbnails, scheduled streams and moderation-pending comments are not modified by these reads.
- Reuses the 0.7.9 whole-transcript evidence engine and final manual review safeguard.

QA: PR #85 Windows Build completed with 303 tests passing, Windows EXE + Inno Setup + update ZIP. Release re-built and checked from main separately.

Note: If YouTube refuses all public transcript providers and no matching NAS SRT exists, extracting the full dialogue is impossible without a trusted local subtitle/transcription source. In that case the application stops safely and asks for a local transcript; it does not request cookies.
