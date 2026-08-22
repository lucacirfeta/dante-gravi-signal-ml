# DANTE v6 reproducibility evidence bundle

This bundle supports the numerical claims in the arXiv v6 continuation and the
self-contained CQG manuscript.  It contains the detector-aware O4a taxonomy,
representation-transition table, final C2 and CQG validation artefacts,
selected per-trial outputs, all 141 PEM null-calibration records, environment
and provenance records, manuscript sources, final figures, the claim contract,
lab notebook and fail-closed verification code.

It deliberately does **not** redistribute GWOSC strain, downloaded auxiliary
channels, credentials, frozen model weights, token caches, pilot runs or stale
archives.  Public strain and auxiliary data remain available from GWOSC.  The
software release is DOI `10.5281/zenodo.21676289`.

## Integrity

`MANIFEST.sha256` records the SHA256 and relative path of every bundled file
except the manifest itself.  `SOURCE_PROVENANCE.json` records both the original
repository SHA256 and the portable bundled SHA256.  A difference is expected
only when a text file contained a machine-local absolute path; such paths are
replaced in the bundle copy by repository-relative or
`GWOSC_RAW_DATA_NOT_BUNDLED` markers.  Scientific arrays, values and source
artefacts in the repository are not modified.

From the repository checkout used to create the archive:

```text
python scripts/build_paper_reproducibility_bundle.py --check
python paper_draft/v6_paper/tools/check_manuscript_claims.py --paper all --verify-artifacts
python scripts/verify_c2_bgv3_artifacts.py --stage all
python scripts/verify_cqg_validation_artifacts.py --stage all
```

After extraction, standard SHA256 tools can verify every line of
`MANIFEST.sha256`; the bundled top-level JSON and CSV artefacts expose the
reported populations, trial-level outcomes, uncertainty summaries and
negative controls without requiring the excluded raw strain or embedding
caches.

## Citation

The final Zenodo DOI for this evidence bundle is intentionally not embedded in
this pre-deposit copy.  Replace this paragraph with the resolvable record DOI
after upload and before journal submission.
