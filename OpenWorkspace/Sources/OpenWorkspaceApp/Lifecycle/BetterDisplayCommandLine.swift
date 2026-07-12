import Darwin
import Dispatch
import Foundation
import OpenWorkspaceCore

enum BetterDisplayCommandLine {
    static func runAndExitIfNeeded() {
        guard let command = CommandLine.arguments.first(where: { $0.hasPrefix("--betterdisplay-") }) else {
            return
        }

        let semaphore = DispatchSemaphore(value: 0)
        var exitCode: Int32 = EXIT_SUCCESS

        Task {
            do {
                try await run(command)
            } catch {
                FileHandle.standardError.write(Data("BetterDisplay command failed: \(error.localizedDescription)\n".utf8))
                exitCode = EXIT_FAILURE
            }
            semaphore.signal()
        }

        semaphore.wait()
        Foundation.exit(exitCode)
    }

    private static func run(_ command: String) async throws {
        let logger = ConsoleLogger(minimumLevel: .error)
        let processRunner = ShellProcessRunner(logger: logger)
        let displayManager = MacDisplayManager(
            provider: BetterDisplayProvider(processRunner: processRunner, logger: logger),
            logger: logger
        )

        switch command {
        case "--betterdisplay-diagnostics":
            let diagnostics = try await displayManager.betterDisplayDiagnostics()
            printDiagnostics(diagnostics)

        case "--betterdisplay-create":
            let before = try await displayManager.refreshDisplays().count
            _ = try await displayManager.createVirtualDisplay()
            try await Task.sleep(for: .seconds(5))
            let after = try await displayManager.refreshDisplays().count
            print("before=\(before)")
            print("afterCreate=\(after)")

        case "--betterdisplay-destroy":
            let before = try await displayManager.refreshDisplays().count
            try await displayManager.destroyVirtualDisplay()
            try await Task.sleep(for: .seconds(5))
            let after = try await displayManager.refreshDisplays().count
            print("before=\(before)")
            print("afterDestroy=\(after)")

        case "--betterdisplay-verify":
            let before = try await displayManager.refreshDisplays().count
            _ = try await displayManager.createVirtualDisplay()
            try await Task.sleep(for: .seconds(8))
            let afterCreate = try await displayManager.refreshDisplays().count
            try await displayManager.destroyVirtualDisplay()
            try await Task.sleep(for: .seconds(8))
            let afterDestroy = try await displayManager.refreshDisplays().count

            print("before=\(before)")
            print("afterCreate=\(afterCreate)")
            print("afterDestroy=\(afterDestroy)")

            guard afterCreate == before + 1, afterDestroy == before else {
                throw OpenWorkspaceError.unsupportedOperation(
                    "BetterDisplay verification expected \(before) -> \(before + 1) -> \(before), got \(before) -> \(afterCreate) -> \(afterDestroy)"
                )
            }

        default:
            throw OpenWorkspaceError.unsupportedOperation(command)
        }
    }

    private static func printDiagnostics(_ diagnostics: BetterDisplayDiagnostics) {
        let environment = diagnostics.environment
        print("installed=\(environment.isInstalled)")
        print("cliAvailable=\(environment.isCLIAvailable)")
        print("version=\(diagnostics.version ?? "unavailable")")
        print("capabilities=\(diagnostics.capabilities.map(\.rawValue).joined(separator: ","))")
        print("executablePermission=\(environment.hasExecutablePermission)")
        print("pathEntryCount=\(environment.pathEntries.count)")
        print("requiredConfigurationLikelyEnabled=\(environment.isRequiredConfigurationLikelyEnabled)")
        print("virtualDisplayConnected=\(diagnostics.virtualDisplayConnected)")
        print("currentDisplayCount=\(diagnostics.currentDisplayCount)")
        print("supportedResolutions=\(diagnostics.supportedResolutions.map { "\($0.width)x\($0.height)" }.joined(separator: ","))")
        for guidance in environment.guidance {
            print("guidance=\(guidance)")
        }
    }
}
