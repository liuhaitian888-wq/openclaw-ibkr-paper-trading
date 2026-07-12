# Development Guide

## Project Layout

- `Sources/OpenWorkspaceApp`: SwiftUI menu-bar app and dependency composition
- `Sources/OpenWorkspaceCore`: testable orchestration core
- `Sources/OpenWorkspaceCore/DisplayManager`: CoreGraphics display listing and provider-backed virtual display lifecycle
- `Sources/OpenWorkspaceCore/StreamingManager`: provider-based host streaming orchestration and Sunshine provider
- `Sources/OpenWorkspaceCore/DeviceDiscovery`: composite discovery service and ADB backend
- `Tests/OpenWorkspaceCoreTests`: unit tests
- `Config`: example configuration only
- `docs`: project documentation
- `.github`: CI, CodeQL, and Dependabot

## Local Checks

```bash
swift build
swift test
pre-commit run --all-files
```

## Menu Bar Lifecycle

Milestone 0 keeps the lifecycle intentionally small and observable.

Debug builds use `NSApplication.ActivationPolicy.regular`, so the Dock icon is visible when launching from Xcode or `swift run`.

Release packaged builds use `LSUIElement=true` in `Packaging/OpenWorkspace.app/Contents/Info.plist` and set `NSApplication.ActivationPolicy.accessory`, so the Dock icon is hidden while the menu-bar item remains visible.

Run lifecycle diagnostics without opening a long-lived GUI session:

```bash
swift run OpenWorkspace --diagnose-lifecycle
```

Create a packaged app bundle:

```bash
Scripts/package_app.sh release
open .build/OpenWorkspace.app
```

Repository instructions require secret scanning before reporting work complete:

```bash
pre-commit run gitleaks --all-files
```

If `pre-commit` is unavailable but `gitleaks` exists:

```bash
gitleaks detect --source . --no-git --redact --verbose
```

## Design Rules

Keep services small and inject dependencies through protocols. Avoid monolithic managers. Prefer Swift, SwiftUI, Combine, and AppKit only where necessary.

Shell processes are allowed only for documented external integration points.

## Prototype Dependencies

The app can launch without BetterDisplay, Sunshine, or ADB. Missing tools are reported as unavailable capabilities.

For a real third-display prototype, install:

- BetterDisplay with `betterdisplaycli`
- Sunshine
- Android Platform Tools

Do not add local paths, serials, IP addresses, or pairing values to committed configuration.
