import Foundation

public enum LogLevel: String, Codable, Comparable, Sendable {
    case debug = "DEBUG"
    case info = "INFO"
    case warning = "WARNING"
    case error = "ERROR"

    private var rank: Int {
        switch self {
        case .debug: 0
        case .info: 1
        case .warning: 2
        case .error: 3
        }
    }

    public static func < (lhs: LogLevel, rhs: LogLevel) -> Bool {
        lhs.rank < rhs.rank
    }
}

public protocol AppLogging: Sendable {
    func log(_ level: LogLevel, _ message: @autoclosure () -> String)
}

public extension AppLogging {
    func debug(_ message: @autoclosure () -> String) {
        log(.debug, message())
    }

    func info(_ message: @autoclosure () -> String) {
        log(.info, message())
    }

    func warning(_ message: @autoclosure () -> String) {
        log(.warning, message())
    }

    func error(_ message: @autoclosure () -> String) {
        log(.error, message())
    }
}

public final class ConsoleLogger: AppLogging, @unchecked Sendable {
    private let minimumLevel: LogLevel
    private let redactor: PrivacyRedacting

    public init(minimumLevel: LogLevel = .info, redactor: PrivacyRedacting = PrivacyRedactor()) {
        self.minimumLevel = minimumLevel
        self.redactor = redactor
    }

    public func log(_ level: LogLevel, _ message: @autoclosure () -> String) {
        guard level >= minimumLevel else { return }
        let safeMessage = redactor.redact(message())
        print("[\(level.rawValue)] \(safeMessage)")
    }
}
