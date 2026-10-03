---
phase: 08-multi-run-productization
plan: 27
verified: 2026-10-03
status: passed
score: 4/4 scoped must-haves verified
---

# 08.27 Verification: transport and numerical comparison only

| Truth | Status | Evidence |
|---|---|---|
| Exact frozen missing contexts only | PASS | Prior report SHA,old receipt SHA,parent and audited geometry;28 identities |
| Official source and exact native samples checked | PASS |28 official MD5 frames,float64 grid/count/finite slice,no resampling |
| Numerical drift fails closed | PASS | Negative regression preserves context/failure;real28/28 exact numerical SHA matches |
| Offline verifier no fetch/admission | PASS | WSL OSexit0,sealedPASS_VERIFIED_RAW_NUMERIC_MATCH_ONLY,explicit false authority flags |

Artifacts substantive/wired:script -> builder -> isolated downloader -> native
slice -> historical comparison; standalone verify -> retained frame checksums
and independent direct HDF5 versus GWPy context reads. Existing directory,
source/config/raw corruption,grid/nonfinite,MD5/lock/failure/partial refusals
tested. Windows/WSL150 PASS each,post-freezeWSL14 PASS;Ruff3 files PASS.

Sourcefreeze71c9f5e and10 dependency SHA checked. Scientific/config/qualified
EOL sources unchanged. Summary/plan parents sealed;zero failure/partial/lock,
28 frames/context files/receipts. Actual run+verify stderr empty,OS exits0.

Wider boundary OPEN:all28 containerSHA differ;no new scientific receipt admitted.
Author decision required before supporting new admission semantics. Native
calibration/clean-install numerical/all-run certification/O4b execution not
completed or activated by this PASS. Local replay is not a second source fetch.
