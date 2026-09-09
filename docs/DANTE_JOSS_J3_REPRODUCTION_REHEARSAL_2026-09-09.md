# DANTE JOSS J3 clean-clone rehearsal

Status: **LOCAL REHEARSAL PASS; INDEPENDENT PUBLIC REPRODUCTION PENDING**

## Scope

This checkpoint exercises the documented Python 3.11 CPU installation and
bounded public technical smoke from a new WSL-native clone at commit
`0d5f395635129d31b4c971f9bce5d6919262c249`. It is not an independent-user
acceptance result, a full corrected-O4a rerun, or a scientific result.

The source commit was cloned from the local repository because the branch had
not been pushed. The smoke correctly rejected the initial `file://` origin.
For the pre-publication rehearsal only, the clone's untracked Git configuration
was changed to the canonical HTTPS repository URL. The tracked checkout stayed
clean. Consequently, this checkpoint validates the installation and smoke
mechanics but does not satisfy the public-source or independent-user parts of
J3.

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
receipt. The automated check did not substitute for the required external
human usability review.

## Remaining J3 gate

After the branch is published, repeat the documented clone and installation
from the public HTTPS repository without altering the remote configuration.
Then ask an external user to execute the CPU smoke and record only:

- source tag/commit and environment identity;
- final status and run key;
- receipt/report hashes;
- whether start, resume, progress, logs, report, and receipt were discoverable;
- any undocumented choice or corrective action that was required.

Do not promote this rehearsal to independent reproduction evidence.
