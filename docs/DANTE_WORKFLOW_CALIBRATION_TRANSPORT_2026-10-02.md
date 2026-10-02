# Calibration transport metadata preflight — 2026-10-02

## Result and boundary

`PASS_PUBLIC_TRANSPORT_METADATA_ONLY`, standalone WSL OS exit0.
All28 exact frozen missing contexts have public HDF5 file-time coverage:
18H1 +10L1,28 distinct file URLs,4096Hz from the scientific contract.
This is NOT sample validity, DQ coverage, historical release equivalence,
recovered raw inputs, calibration or scientific execution readiness.
The28 old content-addressed HDF5 remain absent; no raw download was performed.
O3a science stays closed; no NVIDIA/runtime change or productive job.

## Evidence

- Source freeze `f9ad37642a516d05a8c9108635567e8e16a0f1c8`.
- Report `artifacts/dante_workflow/calibration_transport_v1/preflight_20261002.json`.
- Query completion UTC `2026-10-02T20:03:31.703033+00:00`.
- Report seal `bca8605881953bb399541c2ed67c353e3f672d11c23221b3dc2deda8e0267ca0`.
- Report fileSHA `9dc1c705b036a5ab83888e6438a99d4f221f65f7d489f4ede6efd00446abd48e`.
- Historical receipt fileSHA
  `4f0732510604583e8a02827d3172e337cedd714ed3e8d3b86dfaac6c17b7fe78`.
- Historical parent protocol digest
  `326495389f511b378c52b2a99f7771bd13d87d6852d4191a4f0fb61d6842d4fa`.
- Protocol fileSHA
  `d88535676a73301c329e3f942a140b6557c6499a6fb2fc66eb966f4a7bb875dc`.

Historical receipt location remains
`E:/dante_cache/dante_light/o4a_corrected_v2/inputs_326495389f511b378c52b2a99f7771bd13d87d6852d4191a4f0fb61d6842d4fa/acquisition_manifest.json`.
The prior bounded prior-cache/obvious-archive search found no missing raw copies;
the84 calibration identity containers restored byte-identically in08.25 are a
different input inventory. No broad drive search was extended here.

The official [O4a release](https://gwosc.org/O4/O4a/) links the current
[4kHz R1 archive](https://gwosc.org/archive/O4a_4KHZ_R1/).
The explicit candidate dataset `O4a_4KHZ_R1` is a metadata query choice only,
not a modification or promotion of the scientific contract. The preflight
queries official dataset JSON for EVERY exact padded interval, checks native
rate/detector/dataset and union coverage, and seals selected metadata plus
each complete response SHA. It does not test the data file bytes themselves.
Raw response bodies are not retained; the report retains coverage fields,
not returned strain summary statistics. Endpoint availability is time-bound.

The first exploratory query used run name `O4a` as a dataset and returned404;
the official release link resolved the actual dataset name. This was not a
coverage gap or a reason to substitute another population. No raw request.

## Provenance issue still open

`src/dante_light/o4a_corrected_execution.py::_default_fetcher` calls
`src/core/data_loader.py::fetch_strain_data`, whose remote path invokes
`TimeSeries.fetch_open_data` with sample rate but NO explicit dataset version.
The historical acquisition receipt has file and numerical strain SHA, but no
pinned GWOSC release/calibration identifier. Therefore today's metadata cannot
prove which release produced the old inputs. Do not infer equivalence from
the current release name, date, filename duration or a receipt self-seal.

Next bounded step: acquire the SAME28 contexts into a NEW preserved transport
run, pin official source dataset/files and verify exact rate, `[start,end)`
grid, length, finite raw values and numerical SHA against historical receipt.
No scientific population, threshold, scoring or calibration is changed.

- Byte-identical files can satisfy the existing historical SHA binding.
- Same numerical bytes but changed container SHA need an explicitly reviewed
  new provenance receipt before admission; never edit the old receipt/hash.
- Changed numerical bytes, dtype/grid or missing coverage require stop and
  scientific/provenance review, not tolerance fitting or auto-recalibration.

Actual acquisition and any new receipt admission are NOT authorized by this
preflight increment. No old HDF5, receipt or scientific source was modified.

## Verification

- New transport tests34 PASS; targeted four-file Windows136 PASS/3.72s,
  WSL136 PASS/8.62s; OSexit0 in both.
- Post-freeze WSL34 PASS/1.14s, explicit guest exit0.
- Ruff lint and format on3 files PASS; git diff checks PASS.
- Independent stdlib audit: exact interval set versus SHA-pinned historical
  receipt, report canonical seal/file SHA, cardinalities and false readiness
  flags PASS/OSexit0. Historical raw0/28 still present, receipt unchanged.
- Original protocol/config and three qualified scientific source working SHA
  unchanged, including the existing contracts.py EOL qualification.
- Fail-closed tests cover receipt SHA/parent/seal/identity/grid, metadata
  dataset/detector/rate/origin/duplicates/holes, stitching, raw-URL rejection,
  redirect refusal, audited-reader wiring and concurrent receipt drift.

No full regression rerun was needed for this additive metadata utility; prior
08.25 full Windows349/WSL348+one skip remains evidence for that increment,
not a new empirical claim. No push, main, release, scoring or worker launch.
