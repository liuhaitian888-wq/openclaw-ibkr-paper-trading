import Foundation

public struct SunshineInstallation: Equatable, Sendable {
    public var launchURL: URL
    public var launchArguments: [String]
    public var displayName: String

    public init(launchURL: URL, launchArguments: [String], displayName: String) {
        self.launchURL = launchURL
        self.launchArguments = launchArguments
        self.displayName = displayName
    }
}

public struct SunshineConfiguration: Equatable, Sendable {
    public var url: URL
    public var values: [String: String]

    public init(url: URL, values: [String: String]) {
        self.url = url
        self.values = values
    }
}

public struct SunshineValidationResult: Equatable, Sendable {
    public var isValid: Bool
    public var warnings: [String]

    public init(isValid: Bool, warnings: [String]) {
        self.isValid = isValid
        self.warnings = warnings
    }
}

public protocol SunshineManaging: Sendable {
    func installation() async -> SunshineInstallation?
    func isRunning() async -> Bool
    func start() async throws
    func stop() async throws
    func restart() async throws
    func readConfiguration() async throws -> SunshineConfiguration?
    func validateConfiguration() async throws -> SunshineValidationResult
}

public enum SunshineError: Error, LocalizedError {
    case applicationNotFound
    case stopFailed

    public var errorDescription: String? {
        switch self {
        case .applicationNotFound:
            "Sunshine was not found. Install Sunshine or add its executable to PATH."
        case .stopFailed:
            "Sunshine could not be stopped."
        }
    }
}

public struct SunshineManager: SunshineManaging {
    private let processRunner: ProcessRunning
    private let locator: ExecutableLocator
    private let logger: AppLogging

    public init(
        processRunner: ProcessRunning,
        locator: ExecutableLocator = ExecutableLocator(),
        logger: AppLogging
    ) {
        self.processRunner = processRunner
        self.locator = locator
        self.logger = logger
    }

    public func installation() async -> SunshineInstallation? {
        if let appURL = locator.firstExistingApplication(named: ["Sunshine.app"]) {
            return SunshineInstallation(
                launchURL: URL(fileURLWithPath: "/usr/bin/open"),
                launchArguments: [appURL.path],
                displayName: "Sunshine.app"
            )
        }

        if let executableURL = locator.firstExecutable(named: ["sunshine", "Sunshine"]) {
            return SunshineInstallation(
                launchURL: executableURL,
                launchArguments: [],
                displayName: executableURL.lastPathComponent
            )
        }

        return nil
    }

    public func isRunning() async -> Bool {
        guard let pgrepURL = locator.firstExecutable(named: ["pgrep"]) else {
            return false
        }

        let result = try? await processRunner.capture(pgrepURL, arguments: [
            "-x",
            "Sunshine"
        ])
        if result?.exitCode == 0 {
            return true
        }

        let lowerResult = try? await processRunner.capture(pgrepURL, arguments: [
            "-x",
            "sunshine"
        ])
        return lowerResult?.exitCode == 0
    }

    public func start() async throws {
        guard let installation = await installation() else {
            logger.warning("Sunshine installation was not found")
            throw SunshineError.applicationNotFound
        }
        try await processRunner.run(installation.launchURL, arguments: installation.launchArguments)
        logger.info("Started Sunshine via \(installation.displayName)")
    }

    public func stop() async throws {
        guard await isRunning() else { return }
        guard let pkillURL = locator.firstExecutable(named: ["pkill"]) else {
            throw SunshineError.stopFailed
        }
        try await processRunner.run(pkillURL, arguments: ["-TERM", "-x", "Sunshine"])
        logger.info("Requested Sunshine shutdown")
    }

    public func restart() async throws {
        try await stop()
        try await start()
    }

    public func readConfiguration() async throws -> SunshineConfiguration? {
        guard let url = candidateConfigurationURLs().first(where: { FileManager.default.fileExists(atPath: $0.path) }) else {
            return nil
        }
        let raw = try String(contentsOf: url, encoding: .utf8)
        let values = parseKeyValueConfiguration(raw)
        logger.info("Read Sunshine configuration")
        return SunshineConfiguration(url: url, values: values)
    }

    public func validateConfiguration() async throws -> SunshineValidationResult {
        guard let configuration = try await readConfiguration() else {
            return SunshineValidationResult(
                isValid: false,
                warnings: ["Sunshine configuration was not found."]
            )
        }

        var warnings: [String] = []
        if configuration.values.isEmpty {
            warnings.append("Sunshine configuration has no key-value settings.")
        }
        if configuration.values.keys.contains(where: { $0.localizedCaseInsensitiveContains("password") }) {
            warnings.append("Sunshine configuration appears to contain password-related settings; do not commit it.")
        }
        return SunshineValidationResult(isValid: warnings.isEmpty, warnings: warnings)
    }

    private func candidateConfigurationURLs() -> [URL] {
        let environment = ProcessInfo.processInfo.environment
        let homeURL = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
        var urls: [URL] = []

        if let xdgConfigHome = environment["XDG_CONFIG_HOME"], !xdgConfigHome.isEmpty {
            urls.append(
                URL(fileURLWithPath: xdgConfigHome, isDirectory: true)
                    .appendingPathComponent("sunshine")
                    .appendingPathComponent("sunshine.conf")
            )
        }

        urls.append(
            homeURL
                .appendingPathComponent(".config")
                .appendingPathComponent("sunshine")
                .appendingPathComponent("sunshine.conf")
        )
        urls.append(
            homeURL
                .appendingPathComponent("Library")
                .appendingPathComponent("Application Support")
                .appendingPathComponent("Sunshine")
                .appendingPathComponent("sunshine.conf")
        )

        return urls
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
}
