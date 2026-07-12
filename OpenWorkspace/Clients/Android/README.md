# Android Client Helper

This directory is reserved for the future Kotlin and Jetpack Compose helper application.

Phase 1 only registers an Android display client from the macOS host and delegates streaming to external components. The Android helper must not store serial numbers, MAC addresses, device identifiers, IP addresses, pairing secrets, credentials, tokens, or cookies.

Planned responsibilities:

- Present connection status
- Offer USB and Wi-Fi mode selection
- Launch or deep-link to the selected display client
- Expose user-controlled resolution and FPS preferences
- Avoid unnecessary background services
