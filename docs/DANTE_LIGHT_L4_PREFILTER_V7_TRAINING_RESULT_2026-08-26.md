# DANTE-Light L4 prefilter v7: training-only result

Date: 2026-08-26

Branch: `codex/dante-light-prefilter-v7-selective-deferral`

Scope: exact-teacher ledger and five-member student training only

## Decision

The authorized training increment is complete. All five frozen ensemble
members trained without a numerical failure. The result remains
`TRAINING_COMPLETE_NON_PROMOTABLE`: it does not authorize threshold search,
risk calibration, confirmation access, O4b access, routing, member selection,
or production use.

The next scientific checkpoint is whether to open the already frozen
`threshold_search` partition once. No evidence from that partition has been
accessed in this increment.

## Frozen inputs and access boundary

- training authorization digest:
  `dd8429c03ab6ed810d7c3da568ce2f875c4693fb2a2f9171c281e432f37c1a63`
- training contract digest:
  `03c75c99fc2c3a930601727d49e7dee29284782e3edc263384ad6ee064c9d8f1`
- exact-teacher run key:
  `f83d543049fb913c8323db648466f0120f8ef81458c701e03613db0788807261`
- student run key:
  `dc1858b9c6dc8902b56c5af4d07dd37ffb2098e7f61bca6613880ee6973b0365`
- accessed identities: the 600 frozen training identities only
- protected access lists: empty for `threshold_search`, `risk_calibration`,
  `confirmation`, and O4b

The 600 padded raw windows, exact-teacher batch records, canonical clean-strain
shards, and five model checkpoints are cached under the versioned run
subdirectories of `DANTE_V7_TRAINING_CACHE_ROOT` on drive E. The repository
contains only the compact, hash-bound evidence.

## Exact-teacher ledger

The native O4a teacher was rerun on every training identity through the frozen
production preprocessing and scoring path. The ledger contains 600 rows in 75
batches and has artifact digest
`d28ce069e01eaf400edd588ad0f36c031eb1f6de925fdeb4bba532f8a3b72f20`.

Realized current teacher labels are:

| detector / historical sampling role | rows | current defer label = 1 |
|---|---:|---:|
| H1 / background | 150 | 3 |
| H1 / teacher_positive | 150 | 149 |
| L1 / background | 150 | 7 |
| L1 / teacher_positive | 150 | 147 |

The role names describe the outcome-blind sampling source; the training target
is always the newly recomputed exact-teacher label. The resulting training set
contains 296 positive and 304 negative labels and was not edited after scoring.

### Historical-positive rescore audit

Four of the 300 identities sampled as historical exact-DANTE positives score
below the current frozen detector threshold when recomputed:

| identity | detector | analysis GPS | historical score | current score | threshold |
|---|---|---:|---:|---:|---:|
| `dlv7-a3bf406b7692578b8a981723` | H1 | 1373427680 | 0.2136632353 | 0.0926312804 | 0.1615786119 |
| `dlv7-0b6d535e820973db3df30a8a` | L1 | 1382558176 | 0.2222016901 | 0.0930630490 | 0.1760626833 |
| `dlv7-15f9d1b8c7a5601f9998f8f1` | L1 | 1380089056 | 0.2206279486 | 0.1094822288 | 0.1760626833 |
| `dlv7-aee36ef1870480b71de4f160` | L1 | 1380117728 | 0.2377811819 | 0.0929657295 | 0.1760626833 |

For all four cases, the original 4096-second local O4a block is absent from
`E:/o4a`; the v7 run therefore materialized the public strain into its
hash-bound local cache. Sequential rescoring of the cached windows reproduced
the same current image hashes and scores, excluding thread scheduling or a
transient scorer failure as the cause. The native O4a reference-index SHA256 is
also identical between the historical transition record and the current exact
teacher, excluding index drift. The historical raw/Q-transform input and a
complete teacher/runtime fingerprint were not retained, so one exact cause
cannot be proved from the available provenance. The historical candidate path
did permit incomplete whitening context within its configured edge tolerance,
whereas the current exact path fails closed on incomplete context. Together with
the earlier 58/60 transition reproduction (the other two were refetched or
incomplete local blocks), this supports a raw/context and fail-closed-path
explanation without establishing it for these four identities.

No identity was dropped, replaced, or relabelled from its historical score.
This is a 4/300 (1.33%) drift in the historical sampling stratum, not four
hidden current positives. Downstream descriptions must therefore not call the
stratum "300 current exact-DANTE positives". The current exact labels are the
only training targets and remain the reference for later v7 gates.

## Five-member training result

The five members used the frozen architecture, seeds, optimizer, loss,
balanced detector/role batches, and checkpoint rule. All completed 100 epochs;
the selected epoch is the earliest minimum of equal-detector validation BCE.

| member | selected epoch | equal-detector BCE | H1 BCE | L1 BCE | H1 AUROC | L1 AUROC |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 77 | 0.106381 | 0.053004 | 0.159758 | 1.000000 | 0.994420 |
| 1 | 74 | 0.107572 | 0.033880 | 0.181265 | 1.000000 | 0.969866 |
| 2 | 40 | 0.121448 | 0.042330 | 0.200566 | 1.000000 | 0.974330 |
| 3 | 82 | 0.103128 | 0.040521 | 0.165735 | 1.000000 | 0.986607 |
| 4 | 79 | 0.102687 | 0.036804 | 0.168571 | 1.000000 | 0.992188 |

AUROC is diagnostic only. The high training-partition validation separation
shows that the frozen architecture can learn the case-control target on unseen
training blocks. It does not establish safe selective deferral, protected
morphology retention, a valid operating threshold, positive net compute
saving, later-epoch transfer, or operational readiness.

The five models remain a single frozen ensemble candidate. No best member was
selected and no second-stage distillation was performed. The previously
measured full-ensemble inference cost, rather than a single-member cost, remains
the relevant compute basis for later cost accounting.

## Reproducibility evidence

Compact artifacts:

- `artifacts/dante_light/prefilter_l4_v7_training/teacher_ledger_summary_v7.json`
  - file SHA256:
    `5e294147238e8e72a0e1c2bccefdb431ce62398dfc1f16e65280fa17b9e3eb6c`
- `artifacts/dante_light/prefilter_l4_v7_training/teacher_targets_compact_v7.jsonl`
  - file SHA256:
    `3fa4ab787fd6ffe58d70d4152db8f7c1647af542e922548f86f8db4d2121a6af`
- `artifacts/dante_light/prefilter_l4_v7_training/student_training_summary_v7.json`
  - file SHA256:
    `38f89b1a243299d6e16d621358153e92285821ea41004bbf55e631489c81f681`
  - artifact digest:
    `827260ea03c16ea13771deb8f0c55f1654d88260c6709bfcbfc693458de5b402`

The execution verifier reports `PASS` for authorization and the teacher ledger,
and `PASS_NON_PROMOTABLE` for training. The latter status is intentional and
must not be shortened to an operational PASS.

### Independent checkout audit

The first clean-clone audit exposed that the immutable authorization had been
created from Windows checkout-byte hashes, including mixed LF/CRLF files. This
did not change the executed content or results, but made direct verification
fail on an LF checkout. A retrospective, verification-only bridge now binds
each legacy checkout hash to the corresponding blob in evidence commit
`2cd8bc91c1d4960762ea69098700f93490a8d782` and to its normalized-LF digest.
It does not rewrite the authorization, run keys, or result artifacts, and it
rejects semantic working-tree changes.

At commit `f408f0a`, a fresh GitHub clone with different checkout line endings
passed the full v7 execution verifier and all seven v7 execution regression
tests. The bridge is
`config/dante_light_prefilter_v7_reference_bridge.json`, digest
`6b8f7db6d9b18dad7c202b0fb844cb9af5843548b20cd4599f427ebb9b0a360b`.

## Next checkpoint

The exact-teacher stability amendment is frozen and its eight-window
training-only GPU canary is an exact PASS with all protected access lists empty;
see `DANTE_LIGHT_L4_PREFILTER_V7_TEACHER_STABILITY_AMENDMENT_2026-08-27.md`.
This does not authorize `threshold_search`. Before any future first read of
`threshold_search`, and again before `risk_calibration` and `confirmation`, the
same fingerprint and canary must pass and produce a stage-specific receipt. A
mismatch is `STOP_NO_ACCESS_NO_RETUNE`. Opening `threshold_search` still
requires an explicit scientific decision; confirmation and O4b remain sealed.
