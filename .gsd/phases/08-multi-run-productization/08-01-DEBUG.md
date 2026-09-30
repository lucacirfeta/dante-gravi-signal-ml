---
status: investigating
trigger: "Existing detached UI lifecycle regression timed out during multi-run controller verification"
created: 2026-09-30
updated: 2026-09-30
---

## Current focus

The administrative increment passes the latest complete WSL suite, but the
existing 15-second detached-launch timing regression is intermittent. Do not
claim its timing is fixed or extend/skip the test. No production worker exists.

## Symptoms and evidence

- Initial TDD import error was expected before the adapter factory existed.
- The first profile-only run had 34 PASS/one plan-parity failure: formatting
  occurred between the two source-bound plans, so their Git identity changed.
  Repeated with static sources, the complete controller suite passed 160/one
  Windows-only skip. No identity comparison or provenance gate was bypassed.
- After hardening, complete WSL suite passed 166/one skip in 92.24 seconds.
- After adding one UI adapter-rejection test, one full run had 166 PASS/one
  skip/one existing detached-launch timeout; the isolated existing test also
  timed out at its unchanged 15-second deadline.
- Process inspection found a child running `git diff --binary HEAD --` for
  about 12 seconds. A separate measured diff took 3.93 seconds and emitted
  99,324 lines; WSL sees 256 modified paths while Windows sees only this
  increment's actual tracked changes.
- Windows Git inherits `core.autocrlf=true` from system configuration; WSL's
  `git config --show-origin --get core.autocrlf` returns no configured value.
  This explains divergent line-ending interpretations, not proof of the entire
  launcher timeout's causal chain. Historical qualifications remain untouched.
- No timeout/configuration/source change: the subsequent full WSL suite passed
  167/one skip in 93.37 seconds. Native Windows profile/process tests passed
  48 in 1.34 seconds, including its no-signal process-liveness regression.

## Hypotheses

1. Source-identity collection over a Windows-mounted checkout dominates the
   child deadline: supported by live child Git process and large WSL diff.
2. New adapter dispatch is hanging or changing scientific execution: the
   dispatch is a synchronous pure factory; complete CLI/UI and frozen-command
   parity tests pass. No new scientific process is launched by this increment.
3. Detached child retains capture pipes: not established. Existing launcher
   routes stdout/stderr to separate local test logs; timeout captured no stdout.

## Resolution status

Timing root cause is not fully resolved. Do not normalize frozen scientific
sources, change Git settings, alter source-identity semantics, relax the
deadline, or skip lifecycle tests to turn this warning into a false PASS.
A dedicated clean-checkout/line-ending and launch-duration investigation is
required before claiming portable multi-run release readiness. This is not a
scientific-result failure or authorization for changing historical evidence.
