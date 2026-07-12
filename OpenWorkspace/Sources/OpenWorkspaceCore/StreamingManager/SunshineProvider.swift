import AVFoundation
import Foundation
import Network
import VideoToolbox

public enum StreamingError: Error, LocalizedError {
    case providerUnavailable(String)
    case providerStopFailed(String)

    public var errorDescription: String? {
        switch self {
        case .providerUnavailable(let name):
            "\(name) is not installed or could not be found."
        case .providerStopFailed(let name):
            "\(name) could not be stopped."
        }
    }
}

public struct SunshineProvider: StreamingProvider {
    public let kind: StreamingProviderKind = .sunshine
    public let displayName = "Sunshine"

    private let processRunner: ProcessRunning
    private let locator: ExecutableLocator
    private let redactor: PrivacyRedacting
    private let logger: AppLogging
    private let additionalExecutableDirectories: [String]

    public init(
        processRunner: ProcessRunning,
        locator: ExecutableLocator = ExecutableLocator(),
        redactor: PrivacyRedacting = PrivacyRedactor(),
        logger: AppLogging,
        additionalExecutableDirectories: [String] = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/Applications/Sunshine.app/Contents/MacOS"
        ]
    ) {
        self.processRunner = processRunner
        self.locator = locator
        self.redactor = redactor
        self.logger = logger
        self.additionalExecutableDirectories = additionalExecutableDirectories
    }

    public func installation() async -> StreamingInstallation {
        let executableURL = sunshineExecutableURL()
        let applicationURL = locator.firstExistingApplication(named: ["Sunshine.app"])
        let version = await detectVersion(executableURL: executableURL, applicationURL: applicationURL)
        var guidance: [String] = []

        if executableURL == nil && applicationURL == nil {
            guidance.append("Install Sunshine with: brew tap LizardByte/homebrew && brew install sunshine")
            guidance.append("Sunshine on macOS is experimental and may require Screen Recording, Microphone, and Local Network permissions.")
        }

        return StreamingInstallation(
            isInstalled: executableURL != nil || applicationURL != nil,
            executableURL: executableURL,
            applicationURL: applicationURL,
            version: version,
            guidance: guidance
        )
    }

    public func state() async -> StreamingState {
        await runningProcessIdentifier() == nil ? .stopped : .running
    }

    public func launch() async throws {
        if await state() == .running { return }

        if let executableURL = sunshineExecutableURL() {
            try launchDetached(executableURL, arguments: [])
            logger.info("Started Sunshine executable")
            return
        }

        if let appURL = locator.firstExistingApplication(named: ["Sunshine.app"]) {
            try await processRunner.run(URL(fileURLWithPath: "/usr/bin/open"), arguments: [appURL.path])
            logger.info("Started Sunshine app")
            return
        }

        throw StreamingError.providerUnavailable(displayName)
    }

    public func stop() async throws {
        guard await state() == .running else { return }
        guard let pkillURL = locator.firstExecutable(named: ["pkill"]) else {
            throw StreamingError.providerStopFailed(displayName)
        }

        let result = try await processRunner.capture(pkillURL, arguments: ["-TERM", "-f", "[s]unshine"])
        guard result.exitCode == 0 || result.exitCode == 1 else {
            throw StreamingError.providerStopFailed(displayName)
        }
        try await Task.sleep(for: .seconds(2))
        logger.info("Requested Sunshine shutdown")
    }

    public func restart() async throws {
        try await stop()
        try await Task.sleep(for: .seconds(1))
        try await launch()
    }

    public func reloadConfiguration() async throws {
        try await restart()
    }

    public func readConfiguration() async throws -> StreamingConfiguration {
        let url = configurationURLs().first { FileManager.default.fileExists(atPath: $0.path) }
        guard let url else {
            return StreamingConfiguration(
                url: nil,
                redactedValues: [:],
                validationWarnings: ["Sunshine configuration was not found."]
            )
        }

        let raw = try String(contentsOf: url, encoding: .utf8)
        let values = parseKeyValueConfiguration(raw).mapValues { redactor.redact($0) }
        return StreamingConfiguration(
            url: url,
            redactedValues: values,
            validationWarnings: validate(values: values)
        )
    }

    public func validateConfiguration() async throws -> StreamingConfiguration {
        try await readConfiguration()
    }

    public func readLogs(limit: Int = 80) async throws -> [String] {
        let logs = logURLs()
            .filter { FileManager.default.fileExists(atPath: $0.path) }
            .compactMap { try? String(contentsOf: $0, encoding: .utf8) }
            .flatMap { $0.split(separator: "\n").map(String.init) }

        return Array(logs.suffix(limit)).map { redactor.redact($0) }
    }

    public func statistics() async throws -> StreamingStatistics {
        StreamingStatistics(
            processIdentifier: await runningProcessIdentifier(),
            uptimeSeconds: nil,
            webPortAvailable: await isPortAvailable(47990),
            streamPortsAvailable: await arePortsAvailable([47984, 47989, 48010]),
            videoToolboxAvailable: isVideoToolboxAvailable(),
            hardwareEncoderAvailable: isHardwareEncoderAvailable()
        )
    }

    public func diagnostics() async throws -> StreamingDiagnostics {
        let installation = await installation()
        let state = await state()
        let configuration = try await validateConfiguration()
        let statistics = try await statistics()
        let logs = try await readLogs(limit: 20)

        var issues = configuration.validationWarnings
        if !installation.isInstalled {
            issues.append(contentsOf: installation.guidance)
        }
        if !statistics.videoToolboxAvailable {
            issues.append("VideoToolbox is not available.")
        }
        if !statistics.hardwareEncoderAvailable {
            issues.append("No hardware encoder was detected through VideoToolbox.")
        }

        return StreamingDiagnostics(
            provider: kind,
            installation: installation,
            state: state,
            configuration: configuration,
            statistics: statistics,
            logPreview: logs,
            issues: issues
        )
    }

    public func openSettings() async throws {
        if let openURL = URL(string: "https://localhost:47990") {
            try await processRunner.run(URL(fileURLWithPath: "/usr/bin/open"), arguments: [openURL.absoluteString])
        }
    }

    private func sunshineExecutableURL() -> URL? {
        locator.firstExecutable(
            named: ["sunshine", "Sunshine"],
            additionalDirectories: additionalExecutableDirectories
        )
    }

    private func launchDetached(_ executableURL: URL, arguments: [String]) throws {
        let process = Process()
        process.executableURL = executableURL
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
    }

    private func detectVersion(executableURL: URL?, applicationURL: URL?) async -> String? {
        if let applicationURL {
            let plistURL = applicationURL.appendingPathComponent("Contents/Info.plist")
            if
                let data = try? Data(contentsOf: plistURL),
                let plist = try? PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any],
                let version = plist["CFBundleShortVersionString"] as? String
            {
                return version
            }
        }

        guard let executableURL else { return nil }
        for arguments in [["--version"], ["version"], ["--help"]] {
            let result = try? await processRunner.capture(executableURL, arguments: arguments)
            guard result?.exitCode == 0 else { continue }
            let output = [result?.standardOutput, result?.standardError]
                .compactMap { $0 }
                .joined(separator: "\n")
                .split(separator: "\n")
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .first { !$0.isEmpty }
            if let output {
                return redactor.redact(cleanVersion(output))
            }
        }
        return nil
    }

    private func cleanVersion(_ output: String) -> String {
        guard let range = output.range(of: "Sunshine version:") else {
            return output
        }
        return output[range.lowerBound...]
            .replacingOccurrences(of: "Sunshine version:", with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func runningProcessIdentifier() async -> Int32? {
        guard let pgrepURL = locator.firstExecutable(named: ["pgrep"]) else { return nil }
        let result = try? await processRunner.capture(pgrepURL, arguments: ["-f", "[s]unshine"])
        guard result?.exitCode == 0 else { return nil }
        return result?.standardOutput
            .split(separator: "\n")
            .compactMap { Int32($0.trimmingCharacters(in: .whitespacesAndNewlines)) }
            .first
    }

    private func configurationURLs() -> [URL] {
        let homeURL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
        return [
            homeURL.appendingPathComponent(".config/sunshine/sunshine.conf"),
            homeURL.appendingPathComponent("Library/Application Support/Sunshine/sunshine.conf")
        ]
    }

    private func logURLs() -> [URL] {
        let homeURL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
        return [
            homeURL.appendingPathComponent(".config/sunshine/sunshine.log"),
            homeURL.appendingPathComponent(".config/sunshine/logs/sunshine.log"),
            homeURL.appendingPathComponent("Library/Logs/Sunshine/sunshine.log")
        ]
    }

    private func parseKeyValueConfiguration(_ raw: String) -> [String: String] {
        raw.split(separator: "\n").reduce(into: [:]) { result, line in
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { return }
            let parts = trimmed.split(separator: "=", maxSplits: 1).map(String.init)
            guard parts.count == 2 else { return }
            result[parts[0].trimmingCharacters(in: .whitespaces)] = parts[1].trimmingCharacters(in: .whitespaces)
        }
    }

    private func validate(values: [String: String]) -> [String] {
        var warnings: [String] = []
        if values.keys.contains(where: { $0.localizedCaseInsensitiveContains("password") }) {
            warnings.append("Configuration contains password-related keys; values are redacted and must not be committed.")
        }
        if values.keys.contains(where: { $0.localizedCaseInsensitiveContains("cert") || $0.localizedCaseInsensitiveContains("key") }) {
            warnings.append("Configuration references certificate or key material; do not commit local configuration.")
        }
        return warnings
    }

    private func isVideoToolboxAvailable() -> Bool {
        VTIsHardwareDecodeSupported(kCMVideoCodecType_H264)
    }

    private func isHardwareEncoderAvailable() -> Bool {
        var encoderID: CFString?
        let status = VTCopySupportedPropertyDictionaryForEncoder(
            width: 1920,
            height: 1080,
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: [
                kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder: true
            ] as CFDictionary,
            encoderIDOut: &encoderID,
            supportedPropertiesOut: nil
        )
        return status == noErr
    }

    private func isPortAvailable(_ port: UInt16) async -> Bool {
        guard let lsofURL = locator.firstExecutable(named: ["lsof"]) else { return true }
        let result = try? await processRunner.capture(lsofURL, arguments: ["-nP", "-iTCP:\(port)", "-sTCP:LISTEN"])
        return result?.exitCode != 0
    }

    private func arePortsAvailable(_ ports: [UInt16]) async -> Bool {
        for port in ports where await !isPortAvailable(port) {
            return false
        }
        return true
    }
}
