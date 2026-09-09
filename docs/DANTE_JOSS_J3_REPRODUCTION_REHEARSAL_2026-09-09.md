# DANTE JOSS J3 clean-clone rehearsal

Status: **VERIFIED PUBLIC CLEAN-ENVIRONMENT REPRODUCTION; NO EXTERNAL HUMAN PRE-REVIEW**

## Scope

This checkpoint exercises the documented Python 3.11 CPU installation and
bounded public technical smoke from new WSL-native clones. It is not an
independent-user acceptance result, a full corrected-O4a rerun, or a scientific
result.

The source commit was cloned from the local repository because the branch had
not been pushed. The smoke correctly rejected the initial `file://` origin.
For the pre-publication rehearsal only, the clone's untracked Git configuration
was changed to the canonical HTTPS repository URL. The tracked checkout stayed
clean. Consequently, this checkpoint validates the installation and smoke
mechanics but does not satisfy the public-source or independent-user parts of
J3. After the branch was published, the complete procedure was repeated from a
new clone obtained directly from the canonical GitHub HTTPS remote at commit
`8a807c1b2a91c0483bba9b61f4e32747e226744d`.

## Environment

- WSL-native path outside `/mnt/c`
- Python `3.11.15`
- CPU lock installed from `requirements-cpu.txt`
- package and UI installed with `python -m pip install ".[ui]"`
- package version `3.8.0.dev0`
- platform `Linux-6.6.114.1-microsoft-standard-WSL2-x86_64`

No raw mirror or corrected-O4a cache was copied into the clone.

## Results

| Check | Result |
|---|---|
| Tracked checkout before execution | Clean |
| Installed `dante-workflow` entry point | PASS |
| Installed `dante-workflow-ui` entry point | PASS |
| CPU smoke plan | `SMOKE_PLAN` |
| CPU smoke execution | `PASS_TECHNICAL_SMOKE` |
| Explicit verification | `SKIPPED_VERIFIED_TECHNICAL_SMOKE` |
| Repeat execution/reuse | `SKIPPED_VERIFIED_TECHNICAL_SMOKE` |
| Installed UI dashboard/results discovery | PASS |
| Packaging, smoke-UI, and CLI tests | 14 passed |

The public HTTPS rerun produced run key
`94688ca79c266e7f7c420dccd7fab78b65f27ee7df3c8f79de07e460f9dae944`.
Its verified receipt SHA-256 was
`8b10cafa7335a269d423df10b51b9aafd5415df23a9af2de1b0711a2ab3200c2`;
the readable report SHA-256 was
`9fa828cb8d51fa1c6868bb791a0fa2e0803d32cf1746aec028e3210e888927a5`.
Explicit verification and a subsequent rerun both returned
`SKIPPED_VERIFIED_TECHNICAL_SMOKE`, demonstrating hash-checked reuse.

The smoke run key was
`ca55f8304d5b07ace3693e065e5cc4244f1292cf33e9e37b26c69e11c2419215`.
The verified technical receipt SHA-256 was
`7e86a984d62a64c737eb622bc044a7ab2f691d1da65cd61c6b54d15da2262563`;
the readable report SHA-256 was
`9fa828cb8d51fa1c6868bb791a0fa2e0803d32cf1746aec028e3210e888927a5`.
The report states that two public windows were processed by the paired existing
engines, with no calibration or threshold estimation.

The installed UI exposed the completed phase and `100%`, detailed log links,
the separate verification-results view, the readable report, and the technical
receipt. The maintainer separately exercised the UI and accepted the revised
start, progress, ETA, resume, log, report, and receipt presentation.

The published branch also passed its GitHub-hosted workflow run at
<https://github.com/lucacirfeta/dante-gravi-signal-ml/actions/runs/34353378444>.
This adds a repository-hosted clean worker to the local WSL clean-clone
evidence, but it is still automated evidence.

## Evidence boundary

No external colleague was available to perform a separate pre-submission
reproduction. Therefore J3 closes as verified public clean-environment
reproduction, not as independent human reproduction. This limitation is
recorded rather than replacing the missing review with an automated claim.
The optional
[`DANTE_JOSS_EXTERNAL_REPRODUCTION_CHECKLIST.md`](DANTE_JOSS_EXTERNAL_REPRODUCTION_CHECKLIST.md)
is retained for a future contributor or community reviewer. JOSS reviewers are
expected to install and verify the submitted software independently during the
formal review.

This checkpoint makes no full-O4a reproduction, scientific-result, or
independent-user claim.
