import Foundation
import Testing
@testable import OpenWorkspaceCore

struct SunshineManagerTests {
    @Test func detectsSunshineExecutableFromPathEnvironment() async {
        let locator = ExecutableLocator(environment: ["PATH": "/usr/bin:/bin"])
        let manager = SunshineManager(
            processRunner: MockProcessRunner(),
            locator: locator,
            logger: ConsoleLogger(minimumLevel: .error)
        )

        let installation = await manager.installation()

        #expect(installation == nil)
    }
}

private actor MockProcessRunner: ProcessRunning {
    func run(_ executableURL: URL, arguments: [String]) async throws {}

    func capture(_ executableURL: URL, arguments: [String]) async throws -> ProcessResult {
        ProcessResult(exitCode: 1, standardOutput: "", standardError: "")
    }
}
