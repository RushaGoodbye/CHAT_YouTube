# RG YouTube Control 0.7.6 - 0-quota archive preparation stability

- Handle oversized YouTube descriptions using the exact 5000-byte UTF-8 limit.
- Preserve both official project and donation links and exactly three hashtags.
- Never auto-publish shortened substantive descriptions: prepare a compliant preview as a draft requiring review.
- Preserve the full untouched source description and source tags in the SQLite draft record.
- Avoid repeatedly trying to generate the same draft that is awaiting human review.
- Distinguish ready, needs review, and error counts in the result dialog and work journal.
- Stop inserting generic unverified filler text into short descriptions; send thin material for transcript-grounded review.
- Do not alter video thumbnails, publication settings, or YouTube metadata during zero-quota preparation.
- Regression tests cover seven observed over-limit descriptions with Cyrillic UTF-8 text.

After upgrading, run "Підготувати без квоти" again to process previously blocked videos. The generated review drafts must be checked before publishing.
