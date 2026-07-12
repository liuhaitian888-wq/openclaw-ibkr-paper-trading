import Foundation

public protocol PrivacyRedacting: Sendable {
    func redact(_ value: String) -> String
}

public struct PrivacyRedactor: PrivacyRedacting {
    private let patterns: [(NSRegularExpression, String)]

    public init() {
        let definitions: [(String, String)] = [
            (#"\b(?:\d{1,3}\.){3}\d{1,3}\b"#, "[redacted-ip]"),
            (#"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"#, "[redacted-mac]"),
            (#"(?i)\b(api[_-]?key|token|password|secret|cookie)\s*[:=]\s*[^,\s]+"#, "$1=[redacted-secret]"),
            (#"(?i)\b(serial|device[_-]?id|identifier)\s*[:=]\s*[^,\s]+"#, "$1=[redacted-identifier]")
        ]

        self.patterns = definitions.compactMap { pattern, replacement in
            guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
            return (regex, replacement)
        }
    }

    public func redact(_ value: String) -> String {
        patterns.reduce(value) { partial, entry in
            let range = NSRange(partial.startIndex..<partial.endIndex, in: partial)
            return entry.0.stringByReplacingMatches(
                in: partial,
                options: [],
                range: range,
                withTemplate: entry.1
            )
        }
    }
}
