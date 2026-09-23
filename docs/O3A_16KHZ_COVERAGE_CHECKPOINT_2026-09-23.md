# O3a 16 kHz source-coverage checkpoint

Date: 2026-09-23. Status: **PASS for public file-metadata coverage only**.

The read-only audit `scripts/audit_dante_o3a_16khz_coverage.py` retrieved all
20 pages (9,618 rows including V1) of the GWOSC `O3a_16KHZ_R1` strain-file
API. It required `sample_rate_kHz = 16` on every H1/L1 row, parsed the
`-4096` filename suffix as **frame duration in seconds**, and compared exact
`(gps_start, gps_end)` identities with the frozen 4 kHz inventory. It then
checked continuous frame coverage of every frozen H1/L1 `CBC_CAT1` segment,
including segment endpoints.

| Detector | 16 kHz frames | Frozen 4 kHz frames | Missing/extra frame intervals | CBC_CAT1 segments | Uncovered intervals |
|---|---:|---:|---:|---:|---:|
| H1 | 3,051 | 3,051 | 0 / 0 | 545 | 0 |
| L1 | 3,266 | 3,266 | 0 / 0 | 535 | 0 |

Thus the public 16 kHz inventory has exact temporal-frame parity with the
frozen 4 kHz inventory for both detectors and fully covers the frozen
`CBC_CAT1` population. No CBC_CAT1 population change is needed for missing
16 kHz *file metadata*. The audit read no strain bytes; it does **not** yet
certify every HDF5 payload, sample spacing, content hash, or download
availability. Those remain fail-closed acquisition/preflight checks.

## Scientific decision gate discovered before rerun

The premise that 16 kHz would restore *parity with O4a* does not match the
versioned corrected-O4a method: its native-index contract specifies 4,096 Hz
(`config/dante_o4a_corrected_native_index_v1.json`), as does its raw execution
code. The O4a multiscale reference preflight records GWPy clipping the
requested 2,048 Hz upper frequency to 1,291.0530521679268 Hz. A read-only
synthetic GWPy 4.0.1 probe with the same 32 s, Q=(4,64), 20–2,048 Hz geometry
reproduced 1,291.0530521679268 Hz at 4,096 Hz sampling and reached 2,048 Hz
at 16,384 Hz sampling. The 4 kHz O3a cap is therefore **not established as an
O3a-only dataset limitation**; moving O3a alone to 16 kHz would introduce a
new analysis-band asymmetry relative to the published corrected-O4a method.

The O3a initial seed contract also binds the 4 kHz O4a parity representation
and the historical O3b K=275 index. Changing its sampling rate cannot be
treated as an administrative source substitution. No 16 kHz scientific
contract or run was created. The choice between preserving 4 kHz parity and
opening a separately labeled 16 kHz experimental branch requires explicit
scientific authorization.

The completed 4 kHz calibration, thresholds, scan, cohort, and index remain
unchanged. They must not be silently rebound to 16 kHz. If a distinct 16 kHz
experiment is authorized, it needs new versioned source/representation
contracts and new run keys for initial calibration, thresholds, primary scan,
native cohort, and native index. No score, candidate, or class outcome was
inspected for this coverage decision.
