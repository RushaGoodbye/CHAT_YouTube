# RG Remote bootstrap

## Recommended topology

1. Synology runs RG Remote MCP in Docker.
2. Synology reaches AlexPC over Windows OpenSSH using a dedicated account and key.
3. The MCP container stays bound to NAS localhost only.
4. A separate authenticated HTTPS gateway will be added before connecting ChatGPT externally.
5. GitHub self-hosted runner is the fallback control path.

## One-time AlexPC setup

Run PowerShell as Administrator and use:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\enable_windows_openssh.ps1 -RemoteUser rgremote
```

Create the dedicated `rgremote` local account first. Do not reuse the normal interactive Windows account.

Generate a dedicated SSH key on the NAS and place only its public key in the `rgremote` account's authorized_keys. Put the private key and a pinned known_hosts entry in `rg_remote_mcp/secrets/`.

## One-time Synology MCP setup

Copy `.env.example` to `.env`, verify the two `/volume1/...` volume paths in `docker-compose.yml`, then run from the `rg_remote_mcp` folder:

```sh
docker compose up -d --build
docker compose ps
```

The MCP port is intentionally bound only to `127.0.0.1:8765`.

Smoke test:

```sh
python3 scripts/smoke_client.py
```

Expected result: `RG_REMOTE_MCP_PASS`.

## GitHub runner fallback

For AlexPC, open the repository's Settings -> Actions -> Runners -> New self-hosted runner and copy the short-lived registration token. Then run the included installer from an elevated PowerShell:

```powershell
.\scripts\install_github_runner_windows.ps1 `
  -RepoUrl "https://github.com/RushaGoodbye/CHAT_YouTube" `
  -RegistrationToken "<one-time token>"
```

The runner is labeled `rg, alexpc, windows`.

The repository contains `.github/workflows/rg-remote-control.yml`. It only accepts allow-listed actions from `rg_remote_control/task.json`; arbitrary shell text is rejected.

## Internet exposure

Do not port-forward TCP 8765 and do not publish the raw MCP endpoint. Local deployment and SSH must pass first. External ChatGPT connectivity will be added through authenticated HTTPS/OAuth after the local smoke test is green.
