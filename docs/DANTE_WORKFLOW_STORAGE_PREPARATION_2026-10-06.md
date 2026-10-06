# Storage optimization preparation - no scientific restart

## Preserved stop

Author `stoppa tutto e prepariamo questo` stopped automatic monitoring and the
sole08.40calibration. Monitor PAUSED verified. Scoped SIGINT to confirmed WSL
process group320: controller320, worker604, tracker603; all gone. Supervisor
9907OS1, actualRUN_EXIT_CODE=2 in tool and durable log. Final2997/39971identities,
7session receipts. No failure.json, summary.json, verification.json or lock.
Original controller finally cleaned its lock. No manual deletion or shutdown.

Preserved namespace: `E:\dante_cache\dante_workflow\expanded_calibration_20261006\production_v1`.
Logs remain in its parent. No verifier, resume or calibration PASS. Freeze
ace1b9311879e22af2b02f9891882ff0c3d4b836 and all scientific bytes unchanged.

## Observation, not yet an optimized result

Ryzen7800X3D:8cores/16threads available to WSL. Config primary_calibration:
workers8,batch32,deviceCUDA, inherited unchanged from pinned protocol.07:57Rome
sample: WSL CPU97.3-98.8%idle; RTX5070 GPU0-4%,12GBtotal/~3.5GBallocated.
Only one spawned worker present, usually pipe_read; main frequently waiting
p9_client_rpc. A maximum worker count is not proof of queued parallel work.

Code invokes preprocessing-parent quiet five times per image through nested
guards. SAME separate recursive searches measured0.496s partial+0.474s tmp
on the Windows-backed parent. Multiplying by five suggests material overhead,
but is NOT measured full-path attribution or a guaranteed speedup. Parent
rehashing adds serial work; SIGINT traceback actually ends in guard->_hash.
GPU also intentionally performs the two independent forwards required by the
existing numerical check. Neither that check nor hashing is removed here.

Microsoft recommends keeping Linux-tool workloads on WSL's native filesystem:
[WSL filesystem guidance](https://learn.microsoft.com/en-us/windows/wsl/filesystems).
The proposed comparison changes storage location only. Different backing disks
may confound filesystem attribution; repetitions are warm/uncontrolled-cache,
not cold-cache benchmarks. Actual gain must be measured, not extrapolated.

## Prepared tool

`scripts/benchmark_dante_workflow_storage.py`, module `storage_probe.py`, and
`config/dante_workflow_storage_probe_v1.json`. Two explicitly separate stages:

1. `mirror`: new workspace `/home/atafe/dante_bench/expanded_storage_20261006/probe_v1`;
   copy the entire verified08.38parent to `parent/`, preserving filenames,
   directories and bytes. Full SHA/size inventories, per-copy source/destination
   rehash, final source/mirror byte equivalence. Reject links, overlaps, existing
   workspace, active/failure/tmp/partial evidence. Preserve failed attempts.
2. `measure`: require sealed mirror proof and exact complete inventories;
   SAME quiet function on original and mirror, alternating order. Capture guard
   and full-inventory durations with all hashes retained. Three repetitions
   from the new I/O config, not a changed scientific parameter. New-only timing
   receipt, no automatic repeated measurement or scientific stage afterwards.

The source is08.38preprocessing, NOT interrupted08.40outputs. Copying files is
not admission to a scientific provider. No image/score/threshold interpretation,
HDF5/GWOSC fetch, model load, pipeline invocation or global/default promotion.
No source/config changes to the frozen scientific runner. Full scientific
runtime/index/encoder/scoring/verifier qualification remains pending.

## Validation and next step

82WSL tests PASS:23new I/O fixture/safety cases and59unchanged calibration
regressions;11upstreamwarnings/6.60s. Ruff lint/format3files PASS. Initial format
check requested2newfiles formatting, corrected before final validation.
These are temporary fixtures, not a real mirror, timing result, or08.40post-run
qualification. No real mirror/measurement has been launched in preparation.
Final21frozen scientific/harness/config SHA auditPASS. Real-parent I/O policy
source/profile/summary/verification pins and sealsPASS; workspace does not exist.
No benchmark speedup or numerical equivalence has yet been measured.

Freeze this tested harness before execution. Explicit CLI requires repository
root, config path and exact config SHA, plus `--stage mirror` or `--stage measure`.
First run mirror only, verify receipt/available space, then launch measurement.
Do not chain calibration or verifier. A future scientific run needs a fresh
namespace, tested/frozen implementation and its unchanged full standalone
numerical gate; never resume or overwrite production_v1.

After the storage result, prepare a separately reviewed overlap design for
reading/preprocessing/GPU. Keep worker count/batch32/order/population from the
existing protocol. Changing hash frequency, caching admission or guard semantics
is a critical validation decision requiring author approval, not a perf tweak.
