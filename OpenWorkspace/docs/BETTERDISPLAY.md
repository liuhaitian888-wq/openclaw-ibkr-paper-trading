# BetterDisplay Integration

OpenWorkspace controls virtual displays through BetterDisplay's documented command-line integration. It does not use private Apple display APIs.

## Architecture

`MacDisplayManager` owns display state for OpenWorkspace. It reads active macOS displays through public CoreGraphics display services and delegates virtual display operations to a `DisplayProviding` implementation.

`BetterDisplayProvider` is the first concrete provider. It is responsible for:

- BetterDisplay installation detection
- `betterdisplaycli` detection
- BetterDisplay app version detection
- Capability detection
- Virtual display create, connect, destroy, and status checks
- Resolution, HiDPI scaling, and rotation commands
- Supported resolution discovery through `displayModeList`
- Settings window opening
- Environment diagnostics and user guidance

The menu calls `WorkspaceService`, which calls `DisplayManager`, which calls the provider. This keeps the UI independent from BetterDisplay-specific command syntax.

## CLI Integration

BetterDisplay documents command-line integration through the app binary and the `betterdisplaycli` helper. OpenWorkspace prefers `betterdisplaycli` and falls back to the app binary when available.

Search locations:

- `PATH`
- `/opt/homebrew/bin`
- `/usr/local/bin`
- `/Applications/BetterDisplay.app/Contents/MacOS`

Create a virtual display:

```bash
betterdisplaycli create \
  -devicetype=virtualscreen \
  -virtualscreenname="OpenWorkspace Virtual Display" \
  -aspectWidth=16 \
  -aspectHeight=9 \
  -useResolutionList=on \
  -resolutionList=1920x1080
```

Connect it:

```bash
betterdisplaycli set -namelike="OpenWorkspace Virtual Display" -connected=on
```

Destroy only the OpenWorkspace-managed virtual display:

```bash
betterdisplaycli discard -namelike="OpenWorkspace Virtual Display"
```

Set resolution:

```bash
betterdisplaycli set -namelike="OpenWorkspace Virtual Display" -resolution=2560x1440
```

Set scaling:

```bash
betterdisplaycli set -namelike="OpenWorkspace Virtual Display" -hiDPI=on
```

Set rotation:

```bash
betterdisplaycli set -namelike="OpenWorkspace Virtual Display" -rotation=90
```

Read supported modes:

```bash
betterdisplaycli get -namelike="OpenWorkspace Virtual Display" -displayModeList
```

Open BetterDisplay settings:

```bash
betterdisplaycli set -settingsWindow=on
```

## Diagnostics

The menu exposes `Displays > Diagnostics`. The command-line equivalent is:

```bash
swift run OpenWorkspace --betterdisplay-diagnostics
```

Diagnostics report:

- Installed
- CLI available
- Version
- Capabilities
- Executable permission
- PATH entry count
- Required configuration status
- Virtual display connection status
- Current display count
- Supported resolutions
- Guidance when BetterDisplay or CLI integration is missing

## Manual Verification

Real-machine verification was performed on July 13, 2026 with BetterDisplay 4.3.5 installed through Homebrew cask.

Command:

```bash
swift run OpenWorkspace --betterdisplay-verify
```

Observed result:

```text
before=2
afterCreate=3
afterDestroy=2
```

This command exercises the same `MacDisplayManager` and `BetterDisplayProvider` used by the menu.

## Known Limitations

- BetterDisplay must be installed and running.
- BetterDisplay CLI integration must be enabled under BetterDisplay Settings > Application > Integration.
- Some BetterDisplay features, including rotation on some displays, may require BetterDisplay Pro or framebuffer support.
- OpenWorkspace intentionally targets only `OpenWorkspace Virtual Display` and never runs `betterdisplaycli discard` without an identifier.
- Supported resolution discovery is only available after the virtual display exists and BetterDisplay returns a `displayModeList`.
- Display names shown by OpenWorkspace are generic to avoid persisting hardware identifiers.

## Troubleshooting

If diagnostics say BetterDisplay is missing:

```bash
brew install --cask betterdisplay
```

If diagnostics say the CLI is missing:

```bash
brew install waydabber/betterdisplay/betterdisplaycli
```

The BetterDisplay cask may also provide `/opt/homebrew/bin/betterdisplaycli`.

If CLI commands do not respond:

1. Launch BetterDisplay.
2. Open BetterDisplay Settings > Application > Integration.
3. Enable CLI/notification integration.
4. Re-run `swift run OpenWorkspace --betterdisplay-diagnostics`.

If display count does not return to the original value, run:

```bash
betterdisplaycli discard -namelike="OpenWorkspace Virtual Display"
```

Do not run `betterdisplaycli discard` without an identifier because it can discard all discardable virtual screens.
