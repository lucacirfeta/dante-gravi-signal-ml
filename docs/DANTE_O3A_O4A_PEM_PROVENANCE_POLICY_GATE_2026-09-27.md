# O3a/O4a paired PEM: provenance-policy gate (2026-09-27)

## Scope

The O3a-only five-channel diagnostic PEM and its 12-target visual review are
complete. This note concerns only the separately planned, paired O3a/O4a PEM
comparison in `.gsd/phases/07-o3a-transfer-readiness/07-20-PLAN.md`. No
comparison, O4a bulk fetch, candidate promotion, or new statistic was run.

## Reproduced gate

In WSL `dante_env`, the command

```text
python -m pytest tests/test_dante_o4a_corrected_native_pem.py tests/test_dante_o4a_native_provenance.py tests/test_dante_o4a_pem_raw_replay.py -q
```

returned **6 failed, 11 passed** (11 upstream warnings). Every failure
reaches `ContractError: native provenance git attributes change is not an
approved additive extension` in
`src/dante_light/o4a_native_provenance.py::_require_git_attributes_policy`.
This is a provenance-policy failure, not evidence that an O4a scientific
output changed. The earlier four-failure count in the 07-20 plan described
a narrower test selection and is retained as historical context.

The frozen historical `.gitattributes` rules are all still present. The ten
additions already allowed by `GIT_ATTRIBUTES_ALLOWED_ADDITIONS` are unchanged.
Exactly four current, O3a-specific LF rules are outside that allowlist:

```text
config/dante_o3a_*.json text eol=lf
tests/test_dante_o3a_native_classification.py text eol=lf
tests/test_dante_o3a_native_taxonomy.py text eol=lf
tests/test_dante_o3a_native_thresholds.py text eol=lf
```

Historical `.gitattributes` SHA-256: `0f08d1614b614f90e87da3ab822288eaaffd16bbdfa4e4f42cef384235b07581`.
Current working-tree SHA-256: `5bfec6fc51f4151d28516ba0c035247ea9f93a5ae1d084b8a65c82281ace401b`.
The comparison is additive; no historical rule was removed. The old frozen
reconciliation reference must not be silently rewritten.

## Decision before execution

The narrow proposed resolution is to version an explicit policy extension
allowing only these four O3a LF rules, with a fail-closed regression proving
that removal or any additional unapproved rule still fails. That changes a
frozen provenance acceptance boundary and therefore needs the author's
explicit approval before implementation. The alternative is to leave the
paired O4a arm paused. Removing the LF rules, bypassing the test, or treating
the current red suite as a scientific result is not an acceptable shortcut.

Until this decision and green regression suite, do not start the O4a bulk
frame fetch or paired PEM measurement. GPS 1243231936 remains in the O3a
diagnostic ledger with its dual-detector BURST_CAT2/3 warning; this gate does
not discard or reclassify it.
