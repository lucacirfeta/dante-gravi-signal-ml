# Fresh installed workflow boundary qualification

Scope: administrative package installation and CLI/UI rendering only. No
scientific stage, acquisition, calibration, candidate scan or O4b was launched.
Source checkout: science/o3-transfer-readiness at200c81d; package version3.8.1.
The native completed calibration and interrupted verifier remain unchanged.

## Observed evidence

- Fresh native Linux directory:
  `/home/atafe/dante_bench/installed_boundary_20261006`.
  Git archive of only pyproject.toml/README.md/LICENSE/src/dante_workflow;
  no copied historical data, score or threshold artifacts. Build with existing
  setuptools81.0.0/wheel0.47.0, pip wheel --no-deps --no-build-isolation --no-index.
  Native source/build logs and wheel retained. No dependency/network download.
- Fresh clean base venv (no system-site-packages), installed wheel --no-index/
  --no-deps. ActualBASE_INSTALL_EXIT_CODE=0/terminalOS0. Wheel SHA256:
  `f742eeb1b59e2bbea14e8bfae41e200843bf8a39bcd58383db96f6b0da0ab700`.
- Python -I proves dante_workflow imports from base_env site-packages, not
  checkout PYTHONPATH. Installed CLI and UI entrypoint --help and installed
  administrative plan all succeed, actualINSTALLED_CLI_EXIT_CODE=0/terminalOS0.
  CLI plan uses the source checkout explicitly, as the package contract requires;
  no scientific commands execute. Logs cli.help.log/ui.help.log/installed.plan.json.
- Separate fresh ui_env with system-site-packages, same wheel locally installed.
  Python -I proves workflow import from ui_env site-packages. Existing optional
  Flask3.1.3/waitress3.0.2/dependencies reused, not a clean scientific environment.
  Flask test client returned200 for `/`, `/static/app.css`, `/static/app.js`;
  DANTE HTML and X-Frame-Options:DENY checked. Observed
  INSTALLED_UI_RENDER_3_ROUTES_PASS. This is response/render qualification,
  not a browser visual inspection or full scientific end-to-end run.
- Same-interpreter installed CLI vs checkout-wrapper full plan equality PASS;
  checkout-wrapper actualexit0 and qualification terminalOS0 observed. Expected
  run key731b3823bfb34f1496f4b5f326d362ceb458b3b32824017577ae76d5a41cc99a.
- All18 raw scientific_source_pins in frozen expanded calibration contract
  exactSHA PASS; no source normalization, policy waiver or numerical change.
- Installed `run-readiness --observing-run O4b --detectors H1 L1` actualexit2,
  statusBLOCKED_RUN_PROFILE/scientific_execution_ready:false. Exact blockers:
  MISSING_DETECTOR_METHOD_CONTRACT and MISSING_WORKFLOW_ADAPTER_CONTRACT.
  Catalogue checked_on2026-09-30; live_coverage_checked:false. This observation
  is about the local frozen registry, not current remote data availability.

## Diagnosed administrative fixture failures

Initial multiline Bash orchestration lost its task_dir argument through the
Windows/WSL quoting boundary and mkdir rejected an empty target, before build
or installation. Replaced by explicit absolute paths; no broad file operations.
First UI fixture placed workflow outside cache allowlist; rejected as designed.
Corrected fixture to a workflow child of its isolated cache without changing
application guards. No scientific stage or historical file was affected.

First plan equality compared different Python executable paths (conda vs clean
venv). Command digests deliberately include executable identity. Code diagnosis:
orchestrator.from_spec defaults python_executable to sys.executable and includes
stage command digests in identity. Retest with the same clean base interpreter
passed exact full equality. No fields dropped or hashes/tolerances bypassed.

## Remaining boundaries / author checkpoint

CLI/UI administrative installation is qualified; expanded-provider full-chain
end-to-end and clean installed scientific model/reader replay remain OPEN.
Full native calibration run is complete; stopped independent full replay is
incomplete, not PASS_VERIFIED. None of these short checks replaces that evidence.

O4b needs explicit release/detector/GPS/DQ/population/reference/calibration/null
and validation choices, a versioned method/workflow contract and source/input/
runtime/disk preflight. Historical dante_light O4b epoch files are not silently
promoted into this workflow or used to transplant O4a scores/thresholds. Virgo
requires approved dedicated calibration/reference/null, never H1/L1 null reuse.
Stop for author scientific/structural choices and before actual O4b launch.

No active scientific controller, new monitor, push/main, O3a reopening or shutdown.
Retain temporary build/environments/logs for review; no automatic restart.
