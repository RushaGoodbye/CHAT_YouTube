# RG NAS passive Gatus monitoring (safe installation)

This monitor is independent from Telegram and Cloudflare publishing. It uses
[Gatus](https://github.com/TwiN/gatus) v5.37.0 and Python 3.11 in separate
Docker containers. No new publicly exposed ports are created.

## Safety gates

1. Confirm production NAS is reachable and Docker Compose is functional.
2. Check whether container names rg-nas-gatus / rg-nas-gatus-observer or
   TCP port 18080 are already in use. Abort rather than replace anything.
3. Install only to /volume1/docker/RG_NAS_MONITOR; no changes to working
   Telegram, YouTube, Auto Edit or Cloudflare containers.
4. Do not merge or deploy PR #135 automatically. Its status files are currently
   absent; monitoring should show a RED telegram-components state until that
   telemetry exists. Red is correct and safer than a misleading green status.

## Installation

Use the version-pinned installer in this directory as root after a manual
NAS review. The installer downloads files from a fixed Git commit, creates a
random **local-only** 0600 token, and runs an isolated Docker Compose project.

    sh rg_nas_gatus_install.sh <40-hex-commit-sha>

All files downloaded by the installer stay inside RG_NAS_MONITOR.
It will refuse to overwrite a directory or containers it does not own.

## Runtime and checks

* Gatus dashboard binds to 127.0.0.1:18080 on the NAS.
* The sidecar observer reads ONLY RG_NAS_STATE via a read-only bind mount.
* The observer pushes 3 status flags every 5 minutes to the isolated internal
  Docker hostname gatus:8080. No Telegram Bot API or Cloudflare calls.
* It fails closed on stale status (15 minutes), missing files, or ERROR.
* Gatus heartbeat will detect an inactive observer after 20 minutes.
* No Synology task scheduler changes or root cron installation are required.
* Access from another computer requires a secure SSH forward to the NAS.
* A NAS-hosted monitor cannot detect a *total NAS outage* independently;
  an external checker is required for that case.
* No chat notifications are enabled, preventing monitoring chatter from
  being published in the actual Telegram news channel.

## Verify after installation

    docker inspect -f '{{.State.Running}}' rg-nas-gatus
    docker inspect -f '{{.State.Running}}' rg-nas-gatus-observer
    curl -fsS http://127.0.0.1:18080/ >/dev/null
    python3 /volume1/docker/RG_NAS_MONITOR/rg_nas_gatus_observer_v1.py

The final Python check can return 2 for genuinely stale/broken NAS states;
this is a useful fault signal, not an installer defect.

The auto-generated token and .env file MUST NEVER be pushed to GitHub.
