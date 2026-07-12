import Foundation

public enum OpenWorkspaceError: Error, LocalizedError {
    case unsupportedOperation(String)

    public var errorDescription: String? {
        switch self {
        case .unsupportedOperation(let operation):
            "\(operation) is not implemented in this milestone."
        }
    }
}
