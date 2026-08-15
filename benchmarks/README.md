# DANTE-Light benchmarks

`dante_light_l0_baseline.json` and its JSONL companion freeze the L0
reference measurement for the exact, canonical dual-index scoring path. The
run used eight temporally stratified O4a background windows (four H1 and four
L1), one excluded warm-up, and two measured repeats per window on an NVIDIA
GeForce RTX 5070 under Windows.

Reproduce it from a checkout containing the validated reference indexes and a
local O4a strain mirror:

```console
python scripts/benchmark_dante_light.py --limit 8 --repeat 2 --warmup 1 \
  --local-only --device cuda \
  --output benchmarks/dante_light_l0_baseline.json
```

The JSON report records the exact Git state, environment, representation and
index hashes, selected case IDs, per-stage latency quantiles, RAM/VRAM peaks,
failures, drops, repeat agreement, and the SHA-256 of the row-level JSONL.
The raw strain is deliberately not embedded and machine-local paths are not
published.

## Interpretation

This is a paired engineering baseline, not a universal throughput claim. On
the recorded machine it processed 16 measured windows without failures or
drops at about 1.16 windows/s. Repeated scores and top-k hashes were identical;
the maximum absolute difference from the archived native score was
`1.0430813e-7`, below the frozen `2e-7` acceptance tolerance.

Data access and Q-transform generation account for most measured end-to-end
time. Therefore an optimization that only shares the DINO forward pass cannot
by itself justify a large end-to-end speed claim. Every later DANTE-Light
optimization must be compared on the same selected case IDs and accepted only
if the numerical and fail-closed contracts continue to pass.

The representation contract records the requested 20--2048 Hz band. With the
pinned GWpy Q-transform and Q range 4--64, GWpy warns that the usable upper
frequency is reduced to approximately 1291.05 Hz. This is existing canonical
behavior, not a DANTE-Light modification; it must remain visible in provenance
when environments are compared.

## L1 exact shared-encoder comparison

The L1 pair was measured on the same commit, environment, selected windows,
warm-up, and repeat schedule:

- `dante_light_l1_canonical_control.json`: 1.1616 windows/s;
- `dante_light_l1_shared_encoder.json`: 1.2931 windows/s.

The observed paired throughput ratio is 1.1132 (about 11.3% higher). The shared
path also reduced peak process RSS from about 1536 MiB to 1509 MiB. All 17
row-level outputs have identical input hashes, primary/native scores, and top-k
hashes across the two engines; both measured repeats are exact, and both remain
within the frozen score tolerance.

This result clears the predeclared 10% engineering adoption gate on the
recorded host. It does not imply an 11.3% gain on every GPU or storage system.
The shared path remains opt-in until the later shadow and packaging gates pass.
