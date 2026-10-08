# RG Telegram: private OpenAI tunnel (read-only stage)

**Status: staged. Not deployed on NAS until bootstrap completes.**

This stage replaces the OpenAI demo MCP stub with a separate, restricted
read-only server. Existing `rg-nas-mcp-hub`, Telegram publishing services,
YouTube and Auto Edit remain untouched.

## Public tools (exact allowlist)

- `telegram_system_status`: local state health/status fields
- `telegram_scheduler_status`: scheduler and control-agent heartbeat ages
- `telegram_moderation_status`: filtered watchdog issues for moderation/scanner/queue
- `telegram_publication_alert_status`: filtered watchdog issues for publication,
  Kyiv alerts and minute of silence

Counts of moderation items or messages delivered cannot be determined from
these local files, so the server must not claim they are available or up to date.

## Security boundaries

- Only bind `127.0.0.1:18767/mcp` on the NAS through Docker host networking.
- Mount the single state directory `/volume1/docker/RG_NAS_STATE` read-only.
- **Never mount** Docker socket, RG_SECRETS, bot tokens, or production source.
- Docker `--read-only`, no Linux capabilities, no-new-privileges and resource limits.
- Read only fixed allowlisted local filenames, no arbitrary path API, no command
  execution, file writes or proxying all the NAS MCP Hub tools.
- Long-lived tunnel key mounted as a read-only file, never an env value or CLI argument.
- The original embedded demo tunnel is stopped **only after** the new reader's
  exact tool catalog and a live status call pass. Failures during the switch
  restore the original demo container.

## Install (NAS)

Use `rg_remote_control/nas/bootstrap_openai_telegram_readonly_v1.sh` via
SSH + `sudo sh`. The script downloads pinned sources, builds a dedicated
image, checks its MCP catalog via `smoke.py`, switches the tunnel with rollback
if not ready, and prints `RG_TELEGRAM_TUNNEL_READONLY: READY` only on success.

The connected ChatGPT plugin may need its tool catalog refreshed/reconnected
after the server changes. Never repeat creation of the tunnel or API key.

## Further stages

After ChatGPT successfully calls all four reader tools, implement separate
**explicit** command approval, scoped Telegram operations and audit trails.
Do not expose `telegram_command_run`, `telegram_fs_write_text` or arbitrary
shell/file primitives directly.
