# RG NAS passive monitoring pilot (not deployed)

Uses [Gatus](https://github.com/TwiN/gatus) v5.37.0 and the
standard-library Python observer. This is a **separate, read-only** service;
it does not modify the existing Telegram bot, Cloudflare, MCP, or NAS scheduler.

## Safety gates before activating on Synology

1. Verify production owner of Telegram public publishing. Do not turn on publication here.
2. Verify live NAS state and take a backup of /volume1/docker/RG_NAS_STATE.
3. Complete PR #135 and deploy its scheduler telemetry after NAS staging QA.
4. Install the pilot in its own directory and ensure port 18080 is unused.
5. Enable a **separate Synology Task Scheduler** job at a 5-minute interval for the
   observer, not inside the Telegram scheduler. This is critical: it detects when
   the main scheduler stops. Run only one copy of the observer task.

## Private local install (manual, no public ports)

Copy compose.yaml, config.yaml and rg_nas_gatus_observer_v1.py
to /volume1/docker/RG_NAS_MONITOR on the NAS. Ensure that data/ exists.
Generate one token locally; do **not** commit it to GitHub or display it in logs:

    cd /volume1/docker/RG_NAS_MONITOR
    umask 077
    python3 - <<'PY'
    from pathlib import Path
    import secrets
    token = secrets.token_urlsafe(40)
    Path("token").write_text(token + "\n", encoding="utf-8")
    Path(".env").write_text("GATUS_MONITOR_TOKEN=" + token + "\n", encoding="utf-8")
    PY
    chmod 600 token .env
    docker compose -f compose.yaml config -q
    docker compose -f compose.yaml up -d

Bind is **127.0.0.1:18080 only**. No public ports, extra Telegram bot poller,
or remote Gatus cloud account. Avoid reusing the production Telegram bot token.
Use SSH port forwarding for viewing the dashboard when needed.

## Verification

Read-only dry run:

    python3 rg_nas_gatus_observer_v1.py

The observer deliberately returns nonzero if fresh/healthy telemetry is
unavailable, rather than incorrectly showing green.

Only after confirming Gatus is reachable on NAS loopback:

    python3 rg_nas_gatus_observer_v1.py --push --token-file /volume1/docker/RG_NAS_MONITOR/token

Schedule this explicit --push every 5 minutes as a **separate** Synology task.
Gatus reports errors for stale state (older than 15 minutes), missing files,
invalid timestamps, or non-OK services. An observer that stops sending triggers
Gatus heartbeat failure after 20 minutes.

Current PR #135 (not deployed) adds files required for the
telegram-components check; that check is expected to be red until deployment.
The control-center check is red for status "degraded" by design.

## Scope and limits

* Read-only state inspection; HTTP POST **only** to NAS localhost port 18080.
* Gatus does not enable public publications, Cloudflare cron, or alerts.
* Gatus on the NAS cannot itself alert if the *whole NAS* is offline; a future
  off-NAS watchdog is required.
* Do not run as a root-cron auto-fixer or restart production services automatically.
* Backups and recovery rehearsal are a separate phase (restic).
