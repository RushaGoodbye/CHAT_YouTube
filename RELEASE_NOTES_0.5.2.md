# RG YouTube Control 0.5.2

- Added an internal hidden PowerShell runtime for Windows-only service operations.
- Prefers PowerShell 7 and falls back to Windows PowerShell 5.1.
- Runs without a visible console window, without profiles, and in non-interactive mode.
- Captures stdout/stderr, applies timeouts, and returns clean application errors.
- Added built-in diagnostics for PowerShell availability and version.
- Added automated tests for runtime selection, invocation, failures, and diagnostics.
