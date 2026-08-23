# DANTE-Light L4 prefilter v5: scattering feasibility

Date: 2026-08-23

Scope: WSL-only, label-blind computational feasibility

Status: `COMPLETE_FEASIBILITY_ONLY_NOT_SELECTED`

## Boundary

This experiment measures only the output dimension, same-runtime numerical
determinism, batch-1 CPU cost, and dependency compatibility of one approved
wavelet-scattering transform. It does not measure teacher fidelity, morphology
retention, background reduction, cross-platform transform support, routing
readiness, or scientific independence from exact DANTE.

Only three deterministic synthetic inputs were used: float32 white noise, a
centered impulse, and a linear chirp. Development outcomes, reserved
confirmation, O4b, teacher scores, and morphology labels were not accessed.
The scattering arm was not selected, the v5 protocol was not frozen, and
routing remains disabled.

## Frozen feasibility transform

The benchmark used Kymatio 0.3.0 under its BSD-3-Clause license, installed in an
isolated WSL package directory on the user cache disk rather than any production
environment. The wheel
`kymatio-0.3.0-py3-none-any.whl` had SHA256
`e517113bc98a52795144eb80549f0686ee8a57dbbd9839b935f10dbceba0ec6b`.

The approved transform was PyTorch/CPU `Scattering1D` on a batch of one 32-second
4096-Hz signal, with `J=10`, `Q=(8,1)`, `T=1024`, `max_order=2`, averaging
enabled, oversampling zero, and array output. Thus the maximum averaging scale
is 1024 samples, or 0.25 s.

## Results

The committed artifact digest is
`600c8a72af2aa21f457f704270edb4f45cbdbc5023c7a27fa5ae30f22b863ebc`.

| Quantity | Result |
|---|---:|
| Output shape | 1 x 374 x 128 |
| Output coefficients | 47,872 |
| Repeated outputs | bitwise identical on all three probes |
| CPU repetitions / warm-ups | 100 / 10 |
| Mean batch-1 cost | 163.228 ms |
| Median batch-1 cost | 162.103 ms |
| p95 batch-1 cost | 176.191 ms |
| Minimum / maximum | 144.855 / 197.591 ms |

The timing runtime was WSL2, Python 3.11.15, PyTorch 2.12.1+cu130, NumPy 2.4.6,
SciPy 1.17.1, CPU execution with eight PyTorch threads. These measurements are
environment-specific. In particular, marginal exact-DANTE costs measured in a
different runtime must not be subtracted from them to claim a net saving.

## Compatibility and maintenance finding

Kymatio documents Linux and macOS as its officially supported operating
systems; transformation was therefore intentionally not executed on Windows.
The artifact and verifier remain portable and are checked on Windows without
importing Kymatio.

The canonical `from kymatio.torch import Scattering1D` import fails in the
recorded environment because Kymatio 0.3.0 transitively imports the removed
`scipy.special.sph_harm` symbol. The benchmark could run only through the
package's internal 1-D frontend. No third-party source was patched, but relying
on an internal API is a material maintenance risk. This is consistent with the
absence of a public Kymatio release after September 2022 and must be reassessed
if scattering is proposed for Plan 2.

## Interpretation and next decision

The transform is deterministic and technically executable under the narrowly
recorded Linux runtime. That is not sufficient to make it a v5 arm. Its
47,872-value output and approximately 163-ms preprocessing cost are much less
attractive than the compact students that motivated v5, while the unsupported
public-import path adds operational risk.

The scientifically clean next checkpoint has two choices:

1. exclude scattering from the v5 protocol and retain this negative/limiting
   feasibility result; or
2. propose it for Plan 2 only after accepting the maintenance risk and defining
   a same-runtime cost gate before any development outcomes are opened.

No choice is made by this feasibility artifact.

## Reproduction

The transform runs only in the approved isolated WSL environment:

```text
export PYTHONPATH=/mnt/e/dante_cache/dante_light_prefilter_l4_v5_scattering/python_packages
/home/atafe/miniconda/envs/dante_env/bin/python \
  scripts/run_dante_light_prefilter_v5_scattering_feasibility.py \
  --wheel /mnt/e/dante_cache/dante_light_prefilter_l4_v5_scattering/wheels/kymatio-0.3.0-py3-none-any.whl
```

The committed artifact can be verified on Windows without Kymatio:

```text
python scripts/run_dante_light_prefilter_v5_scattering_feasibility.py --verify
python -m pytest tests/test_dante_light_prefilter_v5_scattering.py -q
```
