# RG Remote MCP

Restricted remote-control bridge intended for Synology NAS + AlexPC.

## Security model

- only configured filesystem roots are exposed;
- path traversal outside roots is rejected;
- commands are executed without a local shell;
- executable names must be in an allow-list;
- SSH destinations are fixed aliases, not model-supplied hosts;
- SSH host keys are verified with mounted known_hosts;
- container binds to 127.0.0.1 by default and must not be exposed directly to the Internet.

## Synology quick start

1. Copy this folder to the NAS.
2. Create `secrets/alexpc_ssh_key` and `secrets/known_hosts`.
3. Copy `.env.example` to `.env` and adjust volume paths/commands.
4. Run:
   `docker compose up -d --build`
5. Local MCP endpoint:
   `http://127.0.0.1:8765/mcp`

For external ChatGPT access, put an authenticated HTTPS gateway in front of this local endpoint. Do not port-forward 8765 directly.

## AlexPC SSH

Use a dedicated Windows account such as `rgremote`, enable OpenSSH Server, install the NAS public key in that account's authorized_keys, and restrict firewall access to the NAS IP where possible.
