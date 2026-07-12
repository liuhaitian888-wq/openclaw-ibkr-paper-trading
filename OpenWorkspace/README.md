# OpenWorkspace

OpenWorkspace is an open-source macOS orchestration app for turning external devices into a unified developer workspace.

The local Mac is always the only computation host. External devices act as display and input clients. OpenWorkspace does not replace Sunshine, Moonlight, Sidecar, or BetterDisplay; it discovers devices, manages virtual displays, launches existing components, restores workspace state, and provides a clean menu-bar experience.

## Milestone 1 Scope

- macOS menu-bar app using SwiftUI `MenuBarExtra`
- Modular orchestration core
- Menu actions for status, device discovery, virtual display creation/destruction, Sunshine control, settings, and quit
- Device discovery with an ADB backend plus placeholders for Bonjour, mDNS, USB, Bluetooth, and Wi-Fi
- Android device registration without persisting serials or device identifiers
- Display manager with a provider abstraction
- BetterDisplay CLI provider for virtual display creation and destruction
- Sunshine lifecycle manager for installation detection, running status, start, stop, restart, configuration read, and validation
- JSON workspace configuration
- Privacy-aware logging
- Unit tests for configuration, redaction, ADB parsing, and Sunshine absence detection
- GitHub Actions, CodeQL, Dependabot, pre-commit, and gitleaks

No custom video encoding, streaming protocol, or decoder is implemented in this milestone.

## Requirements

- macOS 13 or later
- Xcode command line tools
- Swift 6.1 or later
- Optional: Sunshine installed at `/Applications/Sunshine.app`
- Optional: BetterDisplay and `betterdisplaycli` for virtual display creation
- Optional: Android Platform Tools for `adb` device discovery

## Build

```bash
swift build
```

## Test

```bash
swift test
```

## Run

```bash
swift run OpenWorkspace
```

The app launches as a macOS menu-bar application. Use the menu-bar icon to refresh status, discover Android devices through ADB, create or destroy the virtual display through the configured display provider, control Sunshine, and open the local settings directory.

## Package As An App

```bash
Scripts/package_app.sh release
open .build/OpenWorkspace.app
```

Debug launches show a Dock icon. Release app bundles hide the Dock icon through `LSUIElement` while keeping the menu-bar item visible.

## Virtual Display Provider

Apple's documented public APIs can list active displays but do not provide a normal app-level API for creating a user-session virtual monitor. OpenWorkspace therefore uses a `DisplayProvider` abstraction. The first provider shells out to BetterDisplay's CLI when available.

The provider searches for `betterdisplaycli` in `PATH`, common package-manager locations, and the BetterDisplay app bundle. If the provider is unavailable, the app reports a clear error and does not attempt private CoreGraphics or CoreDisplay APIs.

## Sunshine Integration

OpenWorkspace treats Sunshine as an external dependency. It detects launchable app and executable forms, checks running state through system process tools, and can start, stop, or restart Sunshine. It reads candidate configuration locations for validation only and never logs raw configuration content.

## Device Discovery

ADB discovery parses `adb devices -l`, ignores devices that are not ready, and intentionally avoids storing serial numbers, IP addresses, or device identifiers. Devices are represented as generic aliases such as `Android Device 1`.

## Configuration

Template files live in `Config/`:

- `workspace.example.json`
- `device.example.json`
- `runtime-state.example.json`

Real workspace state is written under the user Application Support directory and must not be committed.

## Security Posture

OpenWorkspace must never store API keys, tokens, passwords, private certificates, SSH private keys, personal data, serial numbers, MAC addresses, device identifiers, IP addresses, session tokens, or authentication cookies.

Logs pass through a privacy redactor before output.

Before committing:

```bash
pre-commit run gitleaks --all-files
swift test
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Virtual Display Workflow](docs/VIRTUAL_DISPLAY.md)
- [Installation Guide](docs/INSTALLATION.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Contribution Guide](docs/CONTRIBUTING.md)
- [Roadmap](docs/ROADMAP.md)
- [Licensing](docs/LICENSES.md)
