"""ChatGPT-facing, strictly read-only Telegram monitoring MCP interface."""
from fastmcp import FastMCP
from status_reader import overview, scheduler, moderation, publications_alerts

mcp = FastMCP(name="RG Telegram Read-Only")

@mcp.tool()
def telegram_system_status() -> dict:
    """Read-only NAS state: control plane, watchdog, deploy and scheduler freshness."""
    return overview()

@mcp.tool()
def telegram_scheduler_status() -> dict:
    """Read-only scheduler heartbeats, staleness and last control-agent result."""
    return scheduler()

@mcp.tool()
def telegram_moderation_status() -> dict:
    """Read-only watchdog's scanner, moderation, publishing and queue problems."""
    return moderation()

@mcp.tool()
def telegram_publication_alert_status() -> dict:
    """Read-only publication, Kyiv alert and minute-of-silence watchdog indicators."""
    return publications_alerts()

if __name__ == "__main__":
    # Loopback binding only. Tunnel client shares host namespace.
    mcp.run(transport="http", host="127.0.0.1", port=18767)
