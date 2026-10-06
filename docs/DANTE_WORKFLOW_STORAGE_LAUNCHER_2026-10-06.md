# Detached one-shot storage probe

Original probe_v1 is interrupted/unverified: no processes, observed exit or sealed
mirror. Preserve its namespace and logs. Human reports Codex update; a lifecycle
interruption is plausible, not a demonstrated benchmark/scientific failure.

`scripts/launch_dante_workflow_storage.ps1` creates a hidden worker via Windows
WMI, not Start-Process under the Codex process tree. Worker parent is WmiPrvSE;
system Windows PowerShell modules explicitly loaded, so the bundled pwsh's
module environment does not break Get-FileHash. One new-only claim/log namespace,
raw pinned module/runner/entry/config/launcher bytes, no scheduler or recurrence.
Worker keeps wsl.exe alive and captures its native exit using a live handle.

Python `storage_supervisor.py` captures subprocess PIDs and actual exit codes in
fsync events.jsonl. One mirror then, only after actualOS0 and SAME read_sealed
byte proof, one measure; pins/parent policy rechecked, no retry/resume. The
unchanged original benchmark repeats complete byte inventories and the SAME
quiet guard, with uncontrolled caches and no scientific stage or promotion.
Final supervisor summary has I/O-only boundary, never numerical qualification.

Observed93WSL testsPASS/11knownwarnings/7.53s, RuffPASS. Six Windows lifecycle
checks PASS: caller exitsOS0, WMI child remains alive and later nativeOS0,
wrong hashes/existing namespace refused. Full Windows->WSL tiny fixture:
supervisor/mirror/measure actualOS0, sealed3files381bytes. This proves tested
process separation, NOT immunity to reboot, explicit WSL termination or every
application-update behavior. No actual Codex restart was induced for testing.

New configv2 changes only I/O namespace/authorization. Original3probe raw pins
and all21frozen science raw pins unchanged. Real target
`/home/atafe/dante_bench/expanded_storage_20261006/probe_v2` and new external logs
`E:\dante_cache\dante_workflow\storage_probe_20261006_v2` remain pending launch
until this increment's local source freeze. Monitor remainsPAUSED; calibration
production_v1 remains interrupted. No push/main/O3a/O4b/shutdown.
