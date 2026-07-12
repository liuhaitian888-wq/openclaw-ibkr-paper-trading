import Foundation

public struct ProcessResult: Equatable, Sendable {
    public var exitCode: Int32
    public var standardOutput: String
    public var standardError: String

    public init(exitCode: Int32, standardOutput: String, standardError: String) {
        self.exitCode = exitCode
        self.standardOutput = standardOutput
        self.standardError = standardError
    }
}

public enum ProcessRunnerError: Error, LocalizedError {
    case nonZeroExit(executable: String, exitCode: Int32, stderr: String)

    public var errorDescription: String? {
        switch self {
        case .nonZeroExit(let executable, let exitCode, let stderr):
            "Command \(executable) exited with code \(exitCode): \(stderr)"
        }
    }
}

public protocol ProcessRunning: Sendable {
    func run(_ executableURL: URL, arguments: [String]) async throws
    func capture(_ executableURL: URL, arguments: [String]) async throws -> ProcessResult
}

public actor ShellProcessRunner: ProcessRunning {
    private let logger: AppLogging

    public init(logger: AppLogging) {
        self.logger = logger
    }

    public func run(_ executableURL: URL, arguments: [String] = []) async throws {
        let result = try await capture(executableURL, arguments: arguments)
        guard result.exitCode == 0 else {
            throw ProcessRunnerError.nonZeroExit(
                executable: executableURL.lastPathComponent,
                exitCode: result.exitCode,
                stderr: result.standardError
            )
        }
    }

    public func capture(_ executableURL: URL, arguments: [String] = []) async throws -> ProcessResult {
        let process = Process()
        process.executableURL = executableURL
        process.arguments = arguments

        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe

        try process.run()
        process.waitUntilExit()

        let output = String(
            data: outputPipe.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        ) ?? ""
        let error = String(
            data: errorPipe.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8
        ) ?? ""

        logger.debug("Ran process path=\(executableURL.path) exitCode=\(process.terminationStatus)")
        return ProcessResult(
            exitCode: process.terminationStatus,
            standardOutput: output,
            standardError: error
        )
    }
}
