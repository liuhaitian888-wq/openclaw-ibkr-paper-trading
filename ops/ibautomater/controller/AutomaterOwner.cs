using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Text.Json;
using System.Runtime.InteropServices;
using QuantConnect.IBAutomater;
namespace OpenClaw {
public static class AutomaterOwner {
 public static IEnumerable<string> SafePhases(string text) {
  foreach (string phase in new[]{"IB Automater initialized", "Waiting for 2FA confirmation", "2FA confirmation timeout", "2FA maximum attempts", "Existing session detected", "Auto-restart token expired", "auto-restart login failed", "IBGateway process exited"})
   if ((text ?? "").Contains(phase, StringComparison.OrdinalIgnoreCase)) yield return phase;
 }
 public static int Main(string[] args) {
  var stopped = new ManualResetEventSlim(false);
  using var term = PosixSignalRegistration.Create(PosixSignal.SIGTERM, context => { context.Cancel=true; stopped.Set(); });
  using var intr = PosixSignalRegistration.Create(PosixSignal.SIGINT, context => { context.Cancel=true; stopped.Set(); });
  string file = Environment.GetEnvironmentVariable("OPENCLAW_AUTOMATER_CREDENTIALS") ?? throw new InvalidOperationException("Private credential path required");
  var mode = File.GetUnixFileMode(file);
  if ((mode & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute)) != 0) throw new InvalidOperationException("Credential file must be mode0600");
  using var json = JsonDocument.Parse(File.ReadAllText(file));
  var cfg = json.RootElement;
  if (cfg.GetProperty("trading_mode").GetString() != "paper") throw new InvalidOperationException("Only Paper allowed");
  using var automater = new IBAutomater(Environment.GetEnvironmentVariable("HOME")+"/Jts", "1050", cfg.GetProperty("username").GetString(), cfg.GetProperty("password").GetString(), "paper", 4002, false);
  int failures=0; int pending=0;
  automater.OutputDataReceived += (_, e) => {
   string text = e.Data ?? "";
   foreach (string phase in SafePhases(text)) Console.WriteLine(DateTime.UtcNow.ToString("O")+" "+phase);
  };
  automater.ErrorDataReceived += (_, e) => Console.WriteLine(DateTime.UtcNow.ToString("O")+" AUTOMATER_ERROR_DETAILS_PRIVATE");
  automater.Restarted += (_, e) => { failures=0; Console.WriteLine(DateTime.UtcNow.ToString("O")+" SOFT_RESTART_COMPLETED_REQUIRES_API_RECONCILIATION"); };
  automater.Exited += (_, e) => { Interlocked.Exchange(ref pending,1); Console.WriteLine(DateTime.UtcNow.ToString("O")+" GATEWAY_EXITED"); };
  try {
   var result=automater.Start(false);
   Console.WriteLine(DateTime.UtcNow.ToString("O")+" START_RESULT "+result.ErrorCode);
   if(result.HasError) return 2;
   while(!stopped.Wait(1000)) {
    if(Interlocked.Exchange(ref pending,0)==0) continue;
    if(++failures>3) {Console.WriteLine("RESTART_LIMIT_REQUIRES_OPERATOR");return 3;}
    if(stopped.Wait(TimeSpan.FromSeconds(30*failures))) break;
    result=automater.Start(false);
    Console.WriteLine(DateTime.UtcNow.ToString("O")+" RESTART_RESULT "+result.ErrorCode);
    if(result.HasError) return 2;
   }
   return 0;
  } finally { automater.Stop(); }
 }
}}
