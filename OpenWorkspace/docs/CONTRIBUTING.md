# Contribution Guide

Thanks for helping build OpenWorkspace.

## Expectations

- Keep modules focused and independently testable.
- Do not add custom video encoding, streaming protocols, or decoders.
- Do not copy third-party source code into this repository.
- Document every external dependency and its license.
- Add tests for important behavior.
- Run secret scanning before opening a pull request.

## Security

Never commit credentials, tokens, personal data, serial numbers, MAC addresses, device identifiers, IP addresses, pairing secrets, authentication cookies, private certificates, or local configuration.

Use `.env.example` and `Config/*.example.json` for placeholders.
