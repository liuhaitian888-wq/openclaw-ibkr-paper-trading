import Testing
@testable import OpenWorkspaceCore

struct PrivacyRedactorTests {
    @Test func redactsSensitiveNetworkAndSecretValues() {
        let redactor = PrivacyRedactor()
        let input = "ip 192.168.1.20 mac AA:BB:CC:DD:EE:FF token=abc123 serial=XYZ"

        let output = redactor.redact(input)

        #expect(!output.contains("192.168.1.20"))
        #expect(!output.contains("AA:BB:CC:DD:EE:FF"))
        #expect(!output.contains("abc123"))
        #expect(!output.contains("XYZ"))
    }
}
