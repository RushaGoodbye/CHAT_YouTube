# RG NAS MCP Hub

One MCP server on Synology NAS with three isolated internal contours:

- `youtube` - RG YouTube Control only
- `telegram` - Telegram moderation/publishing stack only
- `auto_edit` - RG Auto Edit only

## Architecture

External client -> `rg-nas-mcp-hub:8765/mcp`

The hub exposes namespaced tools:

- `youtube_*`
- `telegram_*`
- `auto_edit_*`

Internally the hub talks to three worker containers. Workers do not share a filesystem root or Docker network with each other.

### youtube worker

Mounted only to the YouTube Control data tree.

### telegram worker

Mounted only to Telegram deployment/monitoring/control directories.

### auto_edit worker

Mounted only to RG Auto Edit operational directories.

## Isolation guarantees

- each worker has its own Docker network;
- each worker has its own filesystem mounts;
- path traversal outside its worker root is rejected;
- copy operations stay inside the same worker root;
- commands are allow-listed per worker;
- workers are not published to the host;
- only the hub is bound to NAS localhost;
- the hub does not mount project data directly;
- no cross-contour copy/move API exists.

## Local endpoint

`http://127.0.0.1:8765/mcp`

Do not expose TCP 8765 directly to the Internet. External ChatGPT access should be added later through authenticated HTTPS/OAuth.

## Health

The hub `health` tool reports all three worker states independently and returns `degraded` if any contour is unavailable.
