# Pinned QuantConnect IBAutomater adapter

Upstream 5751a0a9baef74a47515b8ce96a39308563d11d4, Apache-2.0; license and original README retained under upstream.
Reuse upstream C# lifecycle, Java Swing login/2FA and native restart session handling. Local changes: reuse DISPLAY=:99 and Xauthority; never pkill peers; preserve Read-Only API and all precautions; private mode0600 agent file; explicit installation path; close 2FA timeout executor; bounded owned process termination. Controller restricts Paper and logs phases without credentials. Existing single systemd Gateway unit must own this controller; never start a second Gateway owner.

Build Java source with javac --release 11 and Premain-Class ibautomater.IBAutomater, then .NET 10 controller. Dependency restore/build is preparation, not a production login acceptance. Credential JSON: username/password/trading_mode=paper; never commit. Activation requires a verified deployment manifest, process lock and user-completed credential entry. Paper account and quote readback after login remain independent acceptance gates; no orders are sent by this component.
