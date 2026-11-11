using System;
using System.Linq;
using OpenClaw;

foreach (var sample in new[] {
    ("Waiting for 2FA confirmation on IBKR mobile app (to be confirmed within 3 minutes). PRIVATE", "Waiting for 2FA confirmation"),
    ("private prefix: 2FA CONFIRMATION TIMEOUT; private suffix", "2FA confirmation timeout"),
    ("Auto-restart token expired PRIVATE", "Auto-restart token expired"),
    ("auto-restart login failed PRIVATE", "auto-restart login failed"),
    ("Existing session detected PRIVATE", "Existing session detected")
}) {
    var phases = AutomaterOwner.SafePhases(sample.Item1).ToArray();
    if (phases.Length != 1 || phases[0] != sample.Item2)
        throw new Exception("Only fixed canonical phases may leave the private owner");
}
if (AutomaterOwner.SafePhases("private arbitrary detail").Any() || AutomaterOwner.SafePhases(null).Any())
    throw new Exception("Unclassified text must stay private");
Console.WriteLine("PASS: early 2FA, failures and unknown text use fixed phases; no Gateway started");
