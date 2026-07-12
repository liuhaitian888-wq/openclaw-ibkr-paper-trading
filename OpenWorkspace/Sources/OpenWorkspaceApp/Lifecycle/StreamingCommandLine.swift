import Darwin
import Dispatch
import Foundation
import OpenWorkspaceCore

enum StreamingCommandLine {
    static func runAndExitIfNeeded() {
        guard let command = CommandLine.arguments.first(where: { $0.hasPrefix("--streaming-") }) else {
            return
        }

        let semaphore = DispatchSemaphore(value: 0)
        var exitCode: Int32 = EXIT_SUCCESS

        Task {
            do {
                try await run(command)
            } catch {
                FileHandle.standardError.write(Data("Streaming command failed: \(error.localizedDescription)\n".utf8))
                exitCode = EXIT_FAILURE
            }
            semaphore.signal()
        }

        semaphore.wait()
        Foundation.exit(exitCode)
    }

    private static func run(_ command: String) async throws {
        let logger = ConsoleLogger(minimumLevel: .error)
        let manager = StreamingManager(
            provider: SunshineProvider(
                processRunner: ShellProcessRunner(logger: logger),
                logger: logger
            )
        )

        switch command {
        case "--streaming-diagnostics":
            let diagnostics = try await manager.diagnostics()
            printDiagnostics(diagnostics)

        case "--streaming-verify":
            try await manager.stop()
            try await Task.sleep(for: .seconds(3))
            let before = await manager.state()

            try await manager.launch()
            try await Task.sleep(for: .seconds(5))
            let afterLaunch = await manager.state()

            try await manager.restart()
            try await Task.sleep(for: .seconds(5))
            let afterRestartOne = await manager.state()

            try await manager.restart()
            try await Task.sleep(for: .seconds(5))
            let afterRestartTwo = await manager.state()

            try await manager.stop()
            try await Task.sleep(for: .seconds(3))
            let afterStop = await manager.state()

            print("before=\(before.rawValue)")
            print("afterLaunch=\(afterLaunch.rawValue)")
            print("afterRestartOne=\(afterRestartOne.rawValue)")
            print("afterRestartTwo=\(afterRestartTwo.rawValue)")
            print("afterStop=\(afterStop.rawValue)")

            guard before == .stopped,
                  afterLaunch == .running,
                  afterRestartOne == .running,
                  afterRestartTwo == .running,
                  afterStop == .stopped
            else {
                throw OpenWorkspaceError.unsupportedOperation("Streaming verification did not complete stopped -> running -> stopped.")
            }

        default:
            throw OpenWorkspaceError.unsupportedOperation(command)
        }
    }

    private static func printDiagnostics(_ diagnostics: StreamingDiagnostics) {
        print("provider=\(diagnostics.provider.rawValue)")
        print("installed=\(diagnostics.installation.isInstalled)")
        print("executableAvailable=\(diagnostics.installation.executableURL != nil)")
        print("version=\(diagnostics.installation.version ?? "unavailable")")
        print("state=\(diagnostics.state.rawValue)")
        print("configuration=\(diagnostics.configuration.url?.path ?? "unavailable")")
        print("videoToolbox=\(diagnostics.statistics.videoToolboxAvailable)")
        print("hardwareEncoder=\(diagnostics.statistics.hardwareEncoderAvailable)")
        print("webPortAvailable=\(diagnostics.statistics.webPortAvailable)")
        print("streamPortsAvailable=\(diagnostics.statistics.streamPortsAvailable)")
        for issue in diagnostics.issues {
            print("issue=\(issue)")
        }
    }
}
