import Darwin
import Foundation

enum DiagnosticsCommand {
    static var shouldRunAndExit: Bool {
        CommandLine.arguments.contains("--diagnose-lifecycle")
    }

    @MainActor
    static func runAndExitIfNeeded() {
        guard shouldRunAndExit else { return }
        print(MenuBarLifecycleDiagnostics.commandLineReport())
        Foundation.exit(EXIT_SUCCESS)
    }
}
