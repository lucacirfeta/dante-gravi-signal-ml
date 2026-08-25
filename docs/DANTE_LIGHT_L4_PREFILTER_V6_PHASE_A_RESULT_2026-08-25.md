# DANTE-Light L4 v6 Phase A result (2026-08-25)

Status: **COMPUTE FEASIBILITY COMPLETE; NO SCIENTIFIC WINNER SELECTED**

Verified artifact:
`artifacts/dante_light/prefilter_l4_v6_design/phase_a_compute_feasibility_v6.json`
(digest `730e59b2845375187a0a99b639ec37901bcd85d5d687aaf204bdb541e12c002f`).

The benchmark used one deterministic 32 s, 4,096 Hz standard-normal synthetic
strain window, float32, batch one, random weights, one CPU thread, and the
available NVIDIA RTX 5070. Teacher scores, labels, training identities,
development, confirmation, and O4b were not accessed.

| Candidate | Parameters | CPU mean / p95 (ms) | CUDA inference mean / p95 (ms) | CUDA transfer + inference mean (ms) | Leaf activation bytes | CUDA incremental peak |
|---|---:|---:|---:|---:|---:|---:|
| unchanged v5 global average | 3,665 | 1.149 / 1.185 | 0.463 / 0.544 | 0.537 | 2.09 MiB | 1.00 MiB |
| teacher top-fraction | 3,665 | 1.165 / 1.207 | 0.503 / 0.557 | 0.582 | 2.09 MiB | 1.00 MiB |
| attention MIL | 3,730 | 1.157 / 1.205 | 0.542 / 0.590 | 0.624 | 2.10 MiB | 1.00 MiB |
| teacher top-fraction, width x2 | 12,705 | 1.806 / 1.851 | 0.510 / 0.553 | 0.585 | 4.19 MiB | 2.00 MiB |

The local encoders emit 256 temporal instances. Applying the frozen fraction
`68/1369` yields 13 retained student instances for both teacher-aligned arms.

## Bounded conclusion

None of the three new graphs is excluded by compute or memory cost on this
host. The aggregation-only arms add little latency relative to the unchanged
v5 baseline, and the x2 capacity arm remains small enough for a controlled
training ablation. Phase A does not distinguish learnability, rank fidelity,
protected retention, call reduction, net saving, or physical sensitivity.

The next legitimate action is a separate Phase-B freeze for fresh training
identities and the factorial objective/aggregation/capacity comparison. In
particular, the exact hybrid value-plus-rank loss, its weight and pair/list
construction, and any smooth top-k temperature remain undecided scientific
parameters. No training should begin until that checkpoint is approved.
