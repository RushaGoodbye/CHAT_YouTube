# RG Telegram R9 — production recovery gate (2026-10-09)

## Confirmed evidence
- R8 read-only NAS admin GET: HTTP 200 /content and /production-state; readiness false.
- Published morning and poll contain Telegram message IDs in Content Hub state.
- explain marked missed, lastError classified AI_DEFER_PROVIDER_COOLDOWN.
- Moderation live state age 4688 sec; publish health age 4216 sec.
- Production blocking stage moderation; publish and receipt checks also stale.
- NAS scheduler heartbeat fresh, watchdog ERROR.
- R9 read-only probe: watchdog/control-plane logs mtime ~6h old, but heartbeat fresh. Log age alone does NOT prove scripts did not run.
- Scheduler log classifier found numerous timeout and traceback string matches, not unique incidents.
- R9 scheduler observability patches exist only on diagnostic branch.

## Recovery sequence and acceptance criteria
1. Classify scheduler traceback and timeout causes using read-only failure counter; for precise root cause inspect locally with secrets redacted.
2. Verify Cloudflare Scheduled Events via Cloudflare observability, not NAS scheduler heartbeat.
3. Verify moderation check advances its liveCheckedAt, with offsetBlocked false and updatesFailed 0.
4. Verify publish health and receipt verification advance on their own cadence.
5. Check published keys and message IDs BEFORE any replay. Never resend morning or poll.
6. Inspect explain missed/cooldown policy; do not auto-replay expired slots or spend AI quota while provider cooldown active.
7. Verify Kyiv alert heartbeat and minute-of-silence ledger independently of general scheduler.
8. Deploy only a narrowly scoped tested fix, retaining rollback SHA. Perform syntax and regression checks and capture proof.
9. After deploy, re-run R8 plus four RG NAS MCP status reads and confirm end-to-end moderation-to-receipt.

## Strict gates
- No production deploy from this diagnostic branch until root cause and rollback are documented.
- No change to existing queue/published keys in diagnosis.
- No blanket reset of watchdog error.
- Do not raise project completion percentage solely for diagnostics.
- Treat no logs as UNKNOWN, not OK.
