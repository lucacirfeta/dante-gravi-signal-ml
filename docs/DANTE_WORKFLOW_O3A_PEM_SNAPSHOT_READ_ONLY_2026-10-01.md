# Native O3a PEM retained-decision snapshot adapter

Date: 2026-10-01. Branch: science/o3-transfer-readiness. Plan 08.14 continues
the author-approved isolated-snapshot architecture A after 08.13. This increment
adds a separate verifier, CLI and tests. It does not change scientific contracts,
original producers, previous read-only guards, historical artefacts or O3a closure.

Local source freeze: `f254b2b`. Complete WSL workflow/native PEM/PatchProducer:
952 PASS, seven skips, 11 upstream warnings, observed OS exit 0 (508.94s).
Windows workflow: 718 PASS, 220 skips, OS exit 0 (316.53s). Final post-freeze
target: WSL 68 PASS/one skip/11 warnings/exit 0 (87.16s); Windows 47 PASS/
22 platform skips/exit 0 (55.26s). Ruff lint/format PASS. Three new Python source
files are byte-identical to Git. No source edit after freeze and no push.

## What this adapter verifies

The installed, unchanged native PEM contract loader, selection preflight and
retained event validator run on a restricted virtual path backed exclusively by
the admitted immutable byte view. This path cannot become a filesystem path;
unsupported writes or missing members refuse rather than fall back to live files.
Archived Python is checked against installed source but never executed.

The actual 08.12 read-only coincidence gate is invoked first, with every upstream
root explicit. Its existing taxonomy/classification/threshold and earlier gates
remain in force. Their approved persistent locks remain held during snapshot PEM
replay and final input/source/sidecar/guard checks. Coincidence and full classified
candidate ledgers from the snapshot must be byte-identical to those verified live
parents. Repository contract/source/compact bytes also bind to current files.
The capture manifest must use exactly these namespace/name roles:

- `repository/<repository-relative path>`: all 44 executed source bindings plus
  the original scientific contract, method reference, declared parent references,
  source inventory/DQ metadata, inventory entry point, original PEM source freeze
  and existing verified native PEM compact. Required/used member closure is exact.
- `parents/native_coincidence_<key>/<primary-or-diagnostic filename>` and
  `parents/native_classification_<key>/native_classified_candidates.jsonl`:
  precisely the three original parent ledgers, with no additions.
- `pem/<original PEM prefix and derived key>/...`: original target/grouped event
  JSONL, summary, per-target event JSON and referenced null calibration files.

All filenames, populations, counts and parameters are obtained from original
contracts and pure helpers, not from chat. Parent roles, source coverage, target
identity, scores, exclusion population and detector-local channel sets stay exact.
Original strict tier/time-shift decisions are recalculated from retained values;
uncalibrated stays uncalibrated, never negative. Individual event files must equal
grouped rows. Original canonical JSONL bytes, SHA/row specifications, the entire
summary and the entire existing compact are reconstructed/checked. Missing,
altered, duplicate/non-finite or extra/unconsumed evidence fails closed.

No original productive verifier is called: it could publish a missing compact.
The new verifier only returns a stdout receipt. Nothing repairs/reseals old data,
cleans a failure, fetches strain/auxiliary data, recalibrates nulls or runs coherence.

## Deliberate limits

This is **retained decision replay**, not independent numerical coherence/null
reproduction. Calibration file hashes/identity and observed maxima/decisions are
checked; raw auxiliary samples, sensor safety and physical mechanism are not.

The original PEM producer has no cooperative lock. Its live failure/partial/cache
guards are observed before and after, including unsafe links, but the adapter
does not claim PEM writer exclusion, atomic historical capture or global upstream
quiescence. Changing a live PEM measurement file after admission cannot change
the snapshot calculation. Changing a live bound parent/source or creating a live
failure/transient cache during replay causes refusal. This distinction is tested.

Admission is in-memory byte ownership, not an execution sandbox against malicious
Python in the same process. An independently pinned, reviewed capture plan is a
trust anchor; self-consistent bytes alone are not scientific approval. No capture
of historical PEM evidence or full historical verification occurred in 08.14.

The public workflow dispatcher remains unchanged. This adapter is not adopted as
a whole-workflow PASS, clean-install certificate or all-run/Virgo readiness claim.
Native Windows can test pure virtual/snapshot readers; the complete chain refuses
before reading evidence because the existing parent exclusion requires POSIX.

## Separate invocation

Module: `src/dante_workflow/o3a_pem_verification.py`.
CLI: `scripts/verify_dante_o3a_pem_evidence.py`.

Use the 08.13 capture facility only with a separately reviewed/pinned exact plan.
The PEM CLI takes immutable archive bytes and explicit live parent roots:

```text
python -B scripts/verify_dante_o3a_pem_evidence.py
  --repository-root /absolute/repository
  --snapshot /absolute/isolated.zip
  --expected-snapshot-sha256 REVIEWED_ARCHIVE_FILE_SHA256
  --expected-plan-sha256 REVIEWED_PLAN_FILE_SHA256
  --pem-external-root /absolute/pem
  --coincidence-external-root /absolute/coincidence
  --taxonomy-external-root /absolute/taxonomy
  --classification-external-root /absolute/classification
  --threshold-external-root /absolute/thresholds
  --rescore-external-root /absolute/rescore
  --calibration-external-root /absolute/calibration
  --index-external-root /absolute/index
  --cohort-external-root /absolute/cohort
  --primary-external-root /absolute/primary
```

The multiline example lists arguments, not a ready shell continuation command.
No run/repair/publish/save option exists. A successful receipt status is
`PASS_O3A_READ_ONLY_PEM_SNAPSHOT_RETAINED_DECISIONS_ONLY`; it contains binding
hashes and explicit scope flags, no scores, null values or verdict counts.
Its nested byte-only snapshot receipt is not upgraded to scientific closure.

## Test and integration qualifications

Main fixtures use disposable scaled populations/events/calibration values. The
original loaders/preflight/event validators are unpatched there; frozen repository
DQ/source/method metadata is read, not historical PEM event outcomes. Earlier
coincidence ancestry is isolated explicitly. Productive/fetch/writer functions
are prohibited, complete bytes/mtimes unchanged on success, original strict
boundaries tested, and resealed semantic/binding changes refused.

A separate linked fixture runs actual 08.12 coincidence reconstruction, observes
its coincidence/classification/taxonomy locks at the PEM contract handoff, then
intentionally refuses before own PEM replay. Taxonomy ancestry and some upstream
contract loaders remain isolated as in that original scaled fixture. This is a
tested real gate handoff, **not** a positive complete-chain scientific certificate.
Main own-stage success plus the linked handoff must not be described as a full
historical chain execution. A frozen repository contract-only virtual smoke reads
metadata without the native PEM compact or historical event/null outcomes.

Initial test import and a missing copied inventory implementation source failed
closed. Only new fixture setup was corrected; no scientific loader/guard was
patched to make the main fixture pass. New guard link refusals tighten the new
adapter only, leaving all original guards unchanged.

Validation counts, observed OS exits, local source freeze and Git byte audit are
recorded in 08-14 SUMMARY/VERIFICATION. Ruff checks the workflow and CLI. Existing
upstream EOL qualifications remain explicit; no source normalization is performed.

The three original native PEM module/entry point/tests and the null-calibration
helper are byte-identical to Git. The coherence helper is not: its working SHA
`48c557db470441c38a0c1bd24e8a07abfca21616f7bdcc3304d2eea3b707652b`
matches the frozen scientific contract, and exact Git LF-to-CRLF reconstruction
reproduces its bytes. Git SHA256 is
`591fe4ce909f0dde7903e40f724e397e2e7e3b202317e9920e8238c0c0f49dea`;
working/Git sizes are 50,859/49,682 bytes. This was diagnosed, not bypassed or
silently normalized. Inherited contracts.py/physical-helper EOL qualifications
still apply; the whole upstream source set is not described as byte-identical Git.

## Next step

Prepare the exact reviewed real capture plan and a bounded complete-chain snapshot
replay, then profile/preflight integration and clean-install scientific verification.
Do not silently infer historical capture authority, quiescence or global PASS from
these unit/integration tests. Full multi-run productization and Virgo validation
remain open, independently of the already closed diagnostic O3a analysis.
