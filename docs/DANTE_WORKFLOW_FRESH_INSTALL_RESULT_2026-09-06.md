# DANTE workflow fresh-install result — 2026-09-06

Status: **PASS for the bounded CPU technical smoke and UI startup only**.
This is not a corrected O4a release receipt or a scientific result.

## Isolated environment

- Fresh HTTPS clone of branch `codex/dante-workflow-productization-v1` at
  commit `44e437859228dd62ff015d0518fa83a3def6b73c`.
- Fresh Conda prefix with Python 3.11.15 and no system site packages.
- `requirements-cpu.txt` installed from lock SHA-256
  `bcb1ae7155654a8b3ea440a65ea54b17711cb57d9a62bb3e0e2cc2aff36b70b1`.
- Optional `requirements-ui.txt` installed afterward; `pip check` passed both
  before and after the optional installation.
- Fresh Torch and Matplotlib cache roots; no local raw/reference cache copied.

The host WSL Python 3.14 lacked `ensurepip`, so a standard-library `venv` could
not be created without changing the machine. The isolated Python 3.11 Conda
prefix was used instead. No package was installed into the host or scientific
environment.

## Portability defect caught and fixed

The first fresh clone materialized
`config/dante_o4a_final_impact_attribution_v1.json` from the canonical LF Git
blob, while the productization contract referenced the Windows CRLF checkout
hash. Validation failed before workflow execution. The file had never been
covered by the repository's explicit LF attributes.

Commit `44e4378` adds the missing `text eol=lf` rule and binds the contract to
the canonical blob SHA-256
`ce409f03ac3cc702a5bcf15d2ea92984d36b02d95196a3625fd0e9152fd69c61`.
The resulting workflow contract digest is
`d1afa8d7100573d8d280bdaa0b37c3be2e1b8e13346d27d55bc132f38d513d00`.
No scientific field or referenced file content changed; the new contract
identity prevents reuse of evidence bound to the non-portable reference.

## Observed acceptance

- Fresh-clone schema/smoke/recovery tests: **32 passed**.
- CPU technical smoke: `PASS_TECHNICAL_SMOKE`, two public H1/L1 windows.
- Run key:
  `a5829cfa6cd292df7c7efc0ff52127b0992d503e5df6bcdf429b6a3d470bb5b8`.
- Technical receipt SHA-256:
  `71872469c0a28098ba72eab0798b85eab9fbff160b2c979f06361a5e3ce921cd`.
- Separate verify and repeated local run both returned
  `SKIPPED_VERIFIED_TECHNICAL_SMOKE` with the same identity.
- Optional Waitress UI startup/reconnect benchmark: PASS, 15 stages, identical
  run key/directory, worker lease survived both UI exits.

## Packaged CLI/UI parity follow-up

The packaged public-smoke UI was then tested from a second fresh HTTPS clone at
commit `143b7539a23c216f323402a2fa2e36a29322c907`, using the same isolated
Python 3.11 environment. `pip check` passed and the complete workflow test set
reported **103 passed, 1 Windows-only skip** in that clone; the equivalent
Windows suite reported **104 passed**.

The CLI first produced run key
`1e35367aa47cab5229e2722d47f99461905cf48d91ebe401f1ce07c5eb15853e`.
Independent CLI verification and repetition both returned
`SKIPPED_VERIFIED_TECHNICAL_SMOKE`. The actual Waitress UI then executed both
Run/resume and Verify through HTTP POSTs. Both detached workers exited, the UI
reported `VERIFIED_TECHNICAL_SMOKE`, and the receipt returned by the UI was
byte-identical to the CLI receipt, SHA-256
`e91c744891dc70ff2aa20e78c11b2f1f5ae4342a445d6a6a9bba90a479308e58`.

The smoke receipt remains only in the isolated clone because it includes local
absolute evidence paths. Its bounded acceptance record is versioned at
`artifacts/dante_workflow/public_smoke_ui_checkpoint_2026-09-06.json`.
P5 is complete. P6 still requires the full corrected-O4a release receipt and
human confirmation that the packaged path needs no undocumented expert choice.
