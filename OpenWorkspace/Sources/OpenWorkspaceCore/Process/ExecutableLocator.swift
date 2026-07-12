import Foundation

public struct ExecutableLocator: Sendable {
    private let environment: [String: String]
    private let includeStandardDirectories: Bool

    public init(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        includeStandardDirectories: Bool = true
    ) {
        self.environment = environment
        self.includeStandardDirectories = includeStandardDirectories
    }

    public func pathEntries() -> [String] {
        pathDirectories()
    }

    public func firstExecutable(named names: [String], additionalDirectories: [String] = []) -> URL? {
        let directories = pathDirectories() + additionalDirectories
        for directory in directories {
            for name in names {
                let url = URL(fileURLWithPath: directory).appendingPathComponent(name)
                if FileManager.default.isExecutableFile(atPath: url.path) {
                    return url
                }
            }
        }
        return nil
    }

    public func firstExistingApplication(named bundleNames: [String]) -> URL? {
        let directories = applicationDirectories()
        for directory in directories {
            for bundleName in bundleNames {
                let url = URL(fileURLWithPath: directory).appendingPathComponent(bundleName)
                if FileManager.default.fileExists(atPath: url.path) {
                    return url
                }
            }
        }
        return nil
    }

    private func pathDirectories() -> [String] {
        let rawPath = environment["PATH"] ?? ""
        let standard = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin"
        ]
        let environmentDirectories = rawPath.split(separator: ":").map(String.init)
        return (environmentDirectories + (includeStandardDirectories ? standard : [])).uniqued()
    }

    private func applicationDirectories() -> [String] {
        [
            "\(NSHomeDirectory())/Applications",
            "/Applications",
            "/Applications/Utilities"
        ]
    }
}

private extension Array where Element: Hashable {
    func uniqued() -> [Element] {
        var seen = Set<Element>()
        return filter { seen.insert($0).inserted }
    }
}
