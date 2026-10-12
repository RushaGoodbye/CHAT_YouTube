# RG YouTube Control 0.7.23 - actions must look clickable

The Today dashboard's SEO review, Ready and Comments cards previously looked like passive statistics despite accepting hidden clicks. The user could not tell where to click.

- Add an explicit **Відкрити чергу →** button next to the review count, always visible for both main and LIVE channels, regardless of today's stream.
- Add **Переглянути →** for Ready packets and **Відкрити →** for comments. Buttons are actual keyboard-focusable Qt widgets, not label-only links.
- Interactive cards now highlight when the mouse moves over them, while the explicit button keeps the layout compact.
- Automated offscreen Qt tests verify the real button signal, accessible name, visibility and related interface wiring.
- No YouTube API writes, draft changes, or thumbnail changes. Background agent keeps the user-approved manual launch policy.
