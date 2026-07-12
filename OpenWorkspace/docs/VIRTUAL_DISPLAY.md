# Virtual Display Workflow

Milestone 1 implements the OpenWorkspace virtual display workflow.

## Engineering Approach

OpenWorkspace uses Apple public APIs for display enumeration and state refresh. `MacDisplayManager` calls CoreGraphics display services to read active displays and keeps an in-memory snapshot for the menu UI.

Apple's public display APIs support listing and configuring displays, but they do not expose a stable public app-level API for creating a standard macOS user-session virtual monitor. OpenWorkspace therefore does not use private Apple APIs.

Virtual display creation and destruction are delegated to a `DisplayProviding` integration boundary. The first provider is `BetterDisplayProvider`, which shells out to BetterDisplay's documented CLI.

## BetterDisplay CLI Usage

OpenWorkspace looks for `betterdisplaycli` or `BetterDisplayCLI` in:

- `PATH`
- `/opt/homebrew/bin`
- `/usr/local/bin`
- `/Applications/BetterDisplay.app/Contents/MacOS`

Create:

```bash
betterdisplaycli create \
  -devicetype=virtualscreen \
  -virtualscreenname="OpenWorkspace Virtual Display" \
  -aspectWidth=16 \
  -aspectHeight=9 \
  -useResolutionList=on \
  -resolutionList=1920x1080
```

Connect:

```bash
betterdisplaycli set -namelike="OpenWorkspace Virtual Display" -connected=on
```

Destroy:

```bash
betterdisplaycli discard -namelike="OpenWorkspace Virtual Display"
```

Check connection:

```bash
betterdisplaycli get -namelike="OpenWorkspace Virtual Display" -connected
```

The app targets only the OpenWorkspace-managed virtual display name. It does not discard all virtual screens.

## Menu Workflow

The menu exposes:

- `Displays > Create Virtual Display`
- `Displays > Destroy Virtual Display`
- `Displays > Refresh Displays`
- `Displays > List Displays`

The display count and display rows are refreshed on app startup and after create, destroy, refresh, or list actions.

## Manual Verification

Expected real-device verification when BetterDisplay is installed:

1. Start with MacBook plus Sidecar: display count is `2`.
2. Choose `Displays > Create Virtual Display`.
3. Choose `Displays > Refresh Displays`.
4. Confirm display count is `3`.
5. Choose `Displays > Destroy Virtual Display`.
6. Choose `Displays > Refresh Displays`.
7. Confirm display count is `2`.
8. Quit and relaunch OpenWorkspace.
9. Confirm the menu still reports the correct display count.

Local verification on this development machine found 2 displays, but BetterDisplay CLI was not installed, so the real 2 -> 3 -> 2 create/destroy cycle could not be completed locally.

## Known Limitations

- BetterDisplay must be installed and CLI integration must be enabled.
- Some BetterDisplay virtual screen features may require a BetterDisplay Pro license.
- Display names from CoreGraphics are intentionally generic to avoid persisting hardware identifiers.
- OpenWorkspace does not yet apply monitor arrangement after creation.
- OpenWorkspace does not yet persist the virtual display handle across app restarts.

## Future Improvements

- Add a first-class provider health screen.
- Add a display arrangement service after create/destroy is reliable.
- Add provider-specific dry-run diagnostics.
- Add user-selectable resolution presets.
- Add integration tests on a macOS runner with BetterDisplay installed.
