import Foundation
import Testing
@testable import OpenWorkspaceCore

struct SunshineProviderTests {
    @Test func reportsUnavailableWhenExecutableIsAbsent() async {
        let locator = ExecutableLocator(environment: ["PATH": ""], includeStandardDirectories: false)
        let provider = SunshineProvider(
            processRunner: MockProcessRunner(),
            locator: locator,
            logger: ConsoleLogger(minimumLevel: .error),
            additionalExecutableDirectories: []
        )

        let installation = await provider.installation()

        #expect(!installation.isInstalled)
        #expect(installation.executableURL == nil)
        #expect(!installation.guidance.isEmpty)
    }

    @Test func stoppedStateWhenNoProcessIsRunning() async {
        let provider = SunshineProvider(
            processRunner: MockProcessRunner(),
            locator: ExecutableLocator(environment: ["PATH": ""], includeStandardDirectories: false),
            logger: ConsoleLogger(minimumLevel: .error),
            additionalExecutableDirectories: []
        )

        let state = await provider.state()

        #expect(state == .stopped)
    }
}

private actor MockProcessRunner: ProcessRunning {
    func run(_ executableURL: URL, arguments: [String]) async throws {}

    func capture(_ executableURL: URL, arguments: [String]) async throws -> ProcessResult {
        ProcessResult(exitCode: 1, standardOutput: "", standardError: "")
    }
}
