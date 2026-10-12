# RG YouTube Control 0.7.21 - accurate SEO review queue

Read-only audit on AlexPC exposed hundreds of persisted `ready` packages which fail the current full-SEO editorial gate; the dashboard showed only 7 saved `draft` rows.

- Review list and Optimization tab badge count *effective* pending editorial reviews, including persisted Ready packages that fail the current gate.
- Review workflow displays only 10 packages at a time to avoid opening hundreds of dialogs.
- Accepting a packet never bypasses the three diverse A/B-title requirement or the existing readiness gate.
- Existing drafts and Ready metadata stay untouched until a person explicitly approves an eligible package.
- Removes silent legacy-draft cleanup when the review list appears empty; no auto-deletion, no YouTube API writes, no thumbnail changes.
- 0.7.20 text, links, tags and titles remain intact.

Re-run the previously reviewed Shoigu draft. The old Ready status is not grounds for publishing without editorial proof.
