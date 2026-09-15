# DANTE O4a provenance public-record and claim map

Status: prepared for 3.8.1 release review

This map binds the public transparency statements to compact, tracked evidence.
It does not elevate diagnostic selections to globally significant events and
does not introduce a new scientific result.

| Public statement | Verifiable evidence |
|---|---|
| The historical `2c20...` working-tree source bytes were not retained or recovered. | `docs/DANTE_O4A_PROVENANCE_TRANSPARENCY_DRAFT_2026-09-12.md`, sections "What was not retained" and "Interpretation and record updates" |
| The remediation reran the frozen chain with Git-recoverable canonical source. | Ten JSON records under `artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/`; canonical source commit `cf774dd059e5b26da205e5abed3073d574e53c30` |
| The final comparison passed and reproduced the retained scientific outputs byte for byte. | `corrected_final_comparison_v2.json`; run `7db808838ce9f0ca4149048ec6257695b9dccfb3e3b16ce382b8e350d2d03371`; contract `ffe704a9771048274a55f03d809deb9c37940081df02e363f96c8b5cd571c548` |
| No scientific result or conclusion changed. | Final comparison evidence plus each stage's `comparison_to_historical`, `scientific_boundary`, and `verification` fields |
| The earlier 12-window check was useful but insufficient to prove the full chain. | Transparency note, section "Why the 2026-09-04 reconciliation was insufficient" |
| Historical failed and superseded attempts remain part of the record. | Transparency note, remediation and final-comparison sections; immutable run directories referenced by each compact record |

## Compact evidence SHA-256

| Stage | File | SHA-256 |
|---|---|---|
| COHORT | `corrected_native_cohort.json` | `a993a73484aa8a89c800a1d624bdef48f9d06a5d2f979ece5dd569a545077c25` |
| INDEX | `corrected_native_index.json` | `926ebb980fcf3457c7955d35343194f8c83bfde257e355c03a503b6e664ef6d3` |
| NATIVE_CALIBRATION | `corrected_native_calibration.json` | `51df26445c304f9e99f359fce9c03a2a7f11d3c35e632792317498b0b5e8c425` |
| RESCORE | `corrected_native_rescore.json` | `d0cf99e5bd5eeb7503d53efd312b5195c06baef6cc4deecce2511f3da0af3570` |
| THRESHOLDS | `corrected_native_thresholds.json` | `fdd3306b804e26adff29616a92fee375e0e232a9b35b1600d510c007a848ee2c` |
| CLASSIFY | `corrected_native_classification.json` | `f002b701e168bebe05d4b71ad118bd16056fca174117ec7b7a47306c90e19108` |
| TAXONOMY | `corrected_native_taxonomy.json` | `925b15fc5d12dd7eac71632cefbaaddcc13ec5b865f4c8e6b4bef609c716efe6` |
| COINCIDENCE | `corrected_native_coincidence.json` | `96c015cb8b270ad5f7457187bd229d642eea41c243806a428ab03467b2029d17` |
| PEM | `corrected_native_pem.json` | `68ecb72785807a8d77e5f02de306a2b185b97010f7e5f79f5c22fdb383d4b5af` |
| COMPARE | `corrected_final_comparison_v2.json` | `9f7591bfb72a20ea6c4f0bce8e7405a02da98fe889b0e203132206d972407e5f` |

The deterministic release bundle embeds these files, their checksums, sizes,
run keys, and contract digests in `MANIFEST.json`. The final release-level ZIP
checksum will be frozen only after the DOI-bound release commit is selected.
