# Streaming Platform

Milestone 2 introduces a generic streaming orchestration layer. It does not implement Moonlight streaming, benchmarking, relay, or dashboards.

## Architecture

`StreamingManager` owns the provider-independent workflow used by the menu and workspace orchestration.

`StreamingProvider` is the integration boundary for host streaming software. Providers expose:

- Installation detection
- Version detection
- Running state
- Launch, stop, and restart
- Configuration reload
- Configuration read and validation
- Redacted log preview
- Runtime statistics
- Diagnostics
- Settings entry point

The first provider is `SunshineProvider`. Future providers can implement the same protocol for RustDesk, Parsec, Steam Link, or other host software without changing the menu workflow.

## Sunshine Integration

OpenWorkspace treats Sunshine as an external dependency. It does not vendor, fork, or modify Sunshine source code.

Detection searches:

- `PATH`
- `/opt/homebrew/bin`
- `/usr/local/bin`
- `/Applications/Sunshine.app/Contents/MacOS`

The official macOS install path is:

```bash
brew tap LizardByte/homebrew
brew install sunshine
```

Sunshine's default macOS configuration directory is:

```text
~/.config/sunshine
```

OpenWorkspace reads `sunshine.conf` for validation only. Values are redacted before display or logging.

## Menu

The menu exposes:

- `Streaming > Status`
- `Streaming > Launch`
- `Streaming > Stop`
- `Streaming > Restart`
- `Streaming > Reload Configuration`
- `Streaming > Logs`
- `Streaming > Statistics`
- `Streaming > Diagnostics`
- `Streaming > Settings`
- `Streaming > Pair Device`

`Pair Device` is intentionally a placeholder for a future Moonlight workflow.

## Diagnostics

Command-line diagnostics:

```bash
swift run OpenWorkspace --streaming-diagnostics
```

Diagnostics include:

- Provider
- Installed
- Executable available
- Version
- State
- Configuration path
- VideoToolbox availability
- Hardware encoder availability
- Web port availability
- Stream port availability
- Configuration warnings

## Verification

Real-machine verification was performed on July 13, 2026 with Sunshine `2026.516.143833` installed through the official LizardByte Homebrew formula.

Command:

```bash
swift run OpenWorkspace --streaming-verify
```

Observed result:

```text
before=stopped
afterLaunch=running
afterRestartOne=running
afterRestartTwo=running
afterStop=stopped
```

This command exercises the same `StreamingManager` and `SunshineProvider` used by the menu.

## Security

OpenWorkspace never commits Sunshine credentials, logs, pairing secrets, certificates, tokens, or local runtime state.

Configuration values and logs pass through the privacy redactor before display. Local Sunshine files remain in the user's home directory and are not copied into the repository.

## Known Limitations

- Sunshine on macOS is experimental.
- The first Sunshine launch may require macOS Screen Recording, Microphone, and Local Network permissions.
- Gamepads are not currently supported by Sunshine on macOS.
- Port checks only report whether common Sunshine ports are already listening.
- `Pair Device` is a placeholder; Moonlight pairing is not implemented in this milestone.
- Statistics are process and environment diagnostics, not stream performance metrics.

## Future Providers

Future providers should implement `StreamingProvider` and keep provider-specific commands behind that protocol. Expected candidates:

- RustDesk
- Parsec
- Steam Link
- Other documented host streaming tools
