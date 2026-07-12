import Foundation
import Testing
@testable import OpenWorkspaceCore

struct ADBDeviceDiscoveryTests {
    @Test func parsesOnlyReadyAndroidDevicesWithoutPersistingIdentifiers() {
        let backend = ADBDeviceDiscoveryBackend(
            processRunner: MockProcessRunner(),
            logger: ConsoleLogger(minimumLevel: .error)
        )
        let output = """
        List of devices attached
        abcdef123456 device product:redmi model:K70 device:foo transport_id:1
        emulator-5554 offline
        192.0.2.10:5555 device product:redmi model:K70 device:foo transport_id:2
        """

        let devices = backend.parseADBDevices(output)

        #expect(devices.count == 2)
        #expect(devices[0].alias == "Android Device 1")
        #expect(devices[0].connectionMode == .usb)
        #expect(devices[1].alias == "Android Device 2")
        #expect(devices[1].connectionMode == .wifi)
        #expect(!devices.map(\.alias).joined().contains("abcdef123456"))
        #expect(!devices.map(\.alias).joined().contains("192.0.2.10"))
    }
}

private actor MockProcessRunner: ProcessRunning {
    func run(_ executableURL: URL, arguments: [String]) async throws {}

    func capture(_ executableURL: URL, arguments: [String]) async throws -> ProcessResult {
        ProcessResult(exitCode: 0, standardOutput: "", standardError: "")
    }
}
