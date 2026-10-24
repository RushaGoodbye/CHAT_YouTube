# RG Telegram News 2.0 — release candidate checkpoint (2026-10-24)

## Confirmed on production NAS (from operator console)

- NAS `192.168.50.32` with `/volume1/docker/RG_TELEGRAM_NEWS_2`.
- P37 guarded worker and probation installed, result `NEWS2_P37_GUARDED_ROLLOUT_PASS` at `2026-10-24T14:46:37Z`; 103 scheduled attempts at deployment, cron active.
- P36 Telegram private message 8033 successfully sent as one-time confirmation in reply to test 8032. This was **not** an automatic callback-worker end-to-end proof.
- P40 read-only live handler inspection result `NEWS2_P40_ACTUAL_HANDLER_READONLY` at `2026-10-24T15:55:17Z`: `process_callback` lines 85–107 **already accept** both `awaiting_photo_review` and `awaiting_moderation`, with SQL update matching those states.
- P39 hotfix failed safely with `STATE_MATCH_DRIFT`, leaving actual live source unchanged. **Do not retry P39**.
- Channel publication remains disabled in the guarded configuration. Never enable it without operator approval and proof of exclusive bot update ownership.

## Current source integrity evidence

- `rg_moderation.py` live source SHA-256 from P40: `2090ca71215f71cef7f72743e8efc9b69ed0fd6d665ff91f98e555eb2f4be0ff`.
- P37 worker Git blob SHA-1: `eceba0756c1de522a24122075c236f4eac5f185e`.
- P37 probation Git blob SHA-1: `8c2fef89eb62af682afe86f1d7034c87248bc61e`.
- P37 backup: `/volume1/docker/RG_TELEGRAM_NEWS_2/operator/p37_backup_20261024T144637233079Z`.

## New offline release test, not yet executed on NAS

`rg_remote_control/nas/rg_news2_p42_offline_integration_release_gate.py` replays the installed worker and handler against separate copies of live SQLite and a mock Telegram API for reject, recheck, similar, approve block, unauthorized actor, and test-button confirmation.

This check writes neither the actual DB nor actual cron, nor sends Telegram or channel messages. Its success can validate local logic and offline UI calls, **but does not prove live incoming Telegram callbacks are free of competing pollers**.

## Remaining operational blocker before declaring production ready

1. Execute P42 offline integration check on NAS and inspect output.
2. Observe a *new*, authorized real moderation click on an active card handled by the scheduled callback worker, with candidate status transition, visible private reply and button removal. No publication.
3. Check competing Telegram `getUpdates` ownership in the deployed Cloudflare alerts worker before enabling any publishing. Do not infer ownership from source code alone.
4. Replace or renew the 7-day probation cron before its automatic expiration at `2026-10-31T13:05:02Z` **only after** proving live callback handling, to avoid silent future shutdown.

## Important safety rules

- Do not run P39 again; its target pattern was incorrect for the actual code.
- Do not generate new test cards unnecessarily or replay archived authentic moderation decisions against production.
- Do not enable `PUBLISH_ENABLED` or `NAS_EXCLUSIVE_OWNER_VERIFIED` unless verified and explicitly approved.
- User requested silent autonomous work. Avoid repeated speculative installers, redundant password requests, and false declarations of full readiness.
