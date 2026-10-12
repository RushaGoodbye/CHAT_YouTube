# RG YouTube Control 0.7.22 - always-visible SEO work

- The Today screen always displays a clickable **Перевірити SEO-пакети** metric card, even when a scheduled stream is the main priority. The card opens Optimization directly with `Потрібно перевірити` selected.
- Shows actual effective-review count including old Ready drafts that fail current checks.
- The **Готово до YouTube** metric no longer counts persisted Ready records that are blocked by the current editorial gate, avoiding misleading figures such as 396.
- Comments and today's stream remain one-click accessible; YouTube and all stored SEO packets are unchanged.
- Updated regression/UI contract tests for the three-card Today layout and accurate Ready calculation.
