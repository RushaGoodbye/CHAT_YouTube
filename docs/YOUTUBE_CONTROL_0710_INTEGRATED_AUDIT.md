# RG YouTube Control 0.7.10 - integrated audit and release gate

Baseline: v0.7.10 (commit e3bd97d56dd655fa53d7cbe73bcdf6554333e369).
Audit branch does not alter the installed application, live YouTube, NAS services, or the release channel.

## Reproduced from screenshot of video Hj0W-gsVUwO (2026-10-09)
- Deep SEO preview shows ONE proposed title, before/after description and tags, despite user requiring THREE clearly shown A/B options.
- Description changes from 3828 to 820 characters; preview provides no per-fact retention evidence or deletion inventory.
- Evidence indicator shows three timeline blocks with citations. This is not the same as verified dialogue boundaries.
- Current preview requires manual judgment to detect lost punchlines and relevant quotations.

## Confirmed code-level findings in v0.7.10
1. ui.py _save_local_seo_result calls _preview_deep_content_package without passing `variants`; the preview method accepts no variants argument. Thus the three A/B titles, even when generated, are not visible in the before/after confirmation screen.
2. ui.py _normalize_local_seo_package removes any variant matching the selected main title. A three-item candidate list that includes the chosen title becomes two A/B alternatives. The save flow then treats fewer than three as needs_review; ambiguity exists between 'three options total' and 'three additional alternatives'.
3. ui.py _save_local_seo_result only flags `len(variants)<3` for manual review; the preview occurs before this safeguard. It is not a complete quality gate over the current title plus alternatives.
4. dialogue_seo.py has `ab_title_issues()` but the _save_local_seo_result path does not call it explicitly before preview or readiness.
5. dialogue_seo.py `preserve_outline_topics()` preserves topic names but cannot independently prove that key quotes, context, time-coded facts, and effective storytelling hooks survived compression.
6. Metadata cache fallback is correctly described as not live; tests must keep confirming no unwarranted publication or quota spend.

## Release-blocking acceptance criteria
- A/B contract explicitly defined: exactly three *total* candidates including the preferred title, or three *alternatives* plus preferred title. The UI and database must use one convention consistently.
- In preview, show all 3 alternatives/candidates with ranking, primary hook, supporting timestamped quote and explicit evidence/source confidence. Reject unsupported hooks.
- Verify transcript coverage; stop with an actionable message when source insufficient; avoid inventing topics or dialogue boundaries.
- Produce a retention report: which grounded topics, names, quotes, decisive moments, URLs and 3 hashtags survive description rewrite; flag omitted important elements; never silently over-compress.
- Keep thumbnail, privacy, scheduling, pending moderation, source metadata and canonical project/donation links intact.
- No YouTube publication by preparation, preview or local unit tests. Run batch cases across realistic short/mid/long transcripts and bot-blocked yt-dlp, plus GUI smoke, metadata regression, ZIP updater, and rollback.
- Only publish a combined release after passing CI AND representative manual real-video review. No forced release version assigned.

## Scope
One comprehensive QA branch and release gate; no single-bug production patches. Prioritize deterministic failures and a clear user-visible workflow.
