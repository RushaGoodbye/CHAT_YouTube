# RG YouTube Control 0.7.7 - Free GitHub Integrations

Free, open-source enhancements tested in PR #82 (Windows Build, 274 tests passed).

- RapidFuzz (MIT) enables conservative near-duplicate SEO tag cleanup across existing content package validation, manual editing and 0-API workflows. Distinct topical search terms remain intact.
- youtube-comment-downloader 0.1.83 (MIT) adds read-only public comment sample export (up to 100 per selected video) to CSV in Downloads from Optimization -> Додатково. No YouTube Data API quota is consumed.
- CSV formula-injection protection for untrusted public comments.
- No thumbnail, channel moderation, pending approvals, replies, likes, scheduled time, video visibility or published metadata is changed by the new research action.
- Existing NAS SRT, yt-dlp, youtube-transcript-api, local Ollama and quota guards remain the main SEO infrastructure; no heavyweight replacement models added.
- Written license and risk assessment of 15 GitHub tools: docs/FREE_GITHUB_TOOLS_AUDIT.md.

Caveat: public YouTube scraping is a best-effort supplementary tool. It can be blocked by YouTube and cannot view authenticated/moderation-pending comments. Mocked tests do not replace testing public-site access on the user's Windows PC.
