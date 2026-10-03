# Admitted context provider: bounded numerical and installed replay

## Scope and result

08.29, authorized by the author's `procedi` after explicit admission08.28.
Source freeze **566ef46**. A separate provider reads only the exact detector
and padded interval recorded in the new admission receipt. It returns the
existing `CompleteContext`/`ContextSource` interface, with the NEW container
hash distinguished from the unchanged historical numerical hash. The
productive reader factory and frozen upstream sources were not modified.

All **28 contexts (18 H1, 10 L1)** passed native-sample equality against
independent exact slices from the verified official frame files. The existing,
unchanged `src/core/patch_producer.py::_worker_preprocess` produced byte-identical
images through both read paths. Analysis duration, padding, sampling rate,
image geometry, Q range, frequency range and colormap come from the unchanged
parent representation; defaults are checked for agreement before measurement.
Whitening still precedes the analysis-window crop, with complete padding.

This is **PASS_ADMITTED_CONTEXT_PREPROCESSING_ONLY**, not a new calibration,
encoder/scorer test, historical score/image reproduction or full pipeline
certification. It compares today's unchanged preprocessing across two input
paths. No score values were read. It does not measure all39971 calibration
contexts. O3a remains diagnostically closed and O4b is not launched.

## Pinned evidence

External directory:
`E:\dante_cache\dante_light\o4a_corrected_v2\calibration_context_replay`.

| Receipt | Invocation | Observed OS exit |
|---|---|---|
| `replay_checkout_20261003_v1.json` | Checkout numerical replay, exec63145 | 0 |
| `replay_installed_20261003_v1.json` | Fresh installed wheel, exec79989 | 0 |

Both JSON files are byte-identical, not merely equal in selected fields:

- File SHA256: `a930a8c9af1809afad35b620f570657674cdd548d3bc4e2955f35a8c77dd3783`.
- Seal: `fcc570a5077bf76d3e64781ae40160a7cf848b5ee2b9f7e1e83404a5dcaacd4f`.
- Admission SHA: `b17d6388ff888d2b0bd332e1c993b56e83ac0c62d53e62a54d0f01e3d09de6f1`.
- Parent protocol SHA: `d88535676a73301c329e3f942a140b6557c6499a6fb2fc66eb966f4a7bb875dc`.
- Old acquisition manifest SHA: `4f0732510604583e8a02827d3172e337cedd714ed3e8d3b86dfaac6c17b7fe78`.

All10 recovery-pinned source hashes, the admission's3 sources, parent and old
manifest remain unchanged. New provider source is byte-identical to its Git
blob. Frame and consumer/source hashes are checked before and after replay.
Existing upstream EOL/provenance qualifications are not normalized away.

## Fresh installation qualification

New wheel built without dependency installation or build isolation; installed
with `--no-deps --no-index` in a fresh venv made using `--system-site-packages`.
The numerical invocation ran outside the checkout with Python `-I -B`, using
`dante_workflow.calibration_contexts --require-installed`. It required the
pinned checkout receipt and compared the complete independently recalculated
sealed result before writing its own new external output.

Installed provider:
`/home/atafe/dante-context-install-JwD6xs/venv/lib/python3.11/site-packages/dante_workflow/calibration_contexts.py`.
All42 installed Python files match checkout bytes; audit OS exit0. Wheel:
`/home/atafe/dante-context-install-JwD6xs/wheels/dante_workflow-3.8.1-py3-none-any.whl`,
SHA `5afffdc02cfb8dd68ccac7d0239600bbc32d7b47b45a7d9cc915a9fed79dabe3`.

The workflow package is freshly installed, but science comes explicitly from
the existing `dante_env` dependencies and pinned checkout `src.core` modules.
This is NOT an independently provisioned or fully isolated scientific runtime.
Runtime recorded in the sealed receipts: NumPy2.4.6, GWPy4.0.1, h5py3.16.0,
SciPy1.17.1, matplotlib3.11.0. No NVIDIA/driver/dependency changes were made.

An initial launch from `/tmp/dante-context-install-HctKNQ` exited1 before
Python could run: WSL restarted and `/tmp` is a tmpfs, so the installation
directory was gone. No installed numerical output existed. Diagnosis used
WSL state, missing-path inspection and `findmnt /tmp`; a new persistent
`/home/atafe` installation resolved the operational issue. No scientific
parameters, inputs, verification comparisons or historical receipts changed.

## Tests and remaining gates

- Nine-file Windows regression: **230 PASS**, observed exit0,23.07s.
- Same WSL regression: **230 PASS**, observed exit0,45.85s,11 upstream warnings.
- Post-freeze WSL provider/PatchProducer/packaging: **53 PASS**, exit0,34.46s,
  11 upstream warnings.
- Ruff lint and format: **PASS**, two new Python files.
- Synthetic tests cover exact detector/interval/grid/type, drift after admission,
  native/hash identity, parent/default mismatch, consumer failure/image mismatch,
  changed frame/population, module identity, installed-flag guard, immutable
  output locations and expected-evidence mismatch. They are not science results.

Next: bounded integration with the existing encoder/index/scorer and an
independent numerical verifier, from frozen weights/reference/config, without
changing methods or launching production. Productive provider activation,
full calibration/runtime/writer-exclusion qualification and dedicated O4b
release/DQ/population/reference/calibration contracts remain separate gates.
Other observing runs and Virgo need their own scientific qualification; this
H1/L1 fixture does not certify them. Local commits only, no push/main/release.
User-untracked folders and historical runs are preserved.
