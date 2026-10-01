# Isolated retained-evidence snapshot foundation

Date: 2026-10-01. Branch: science/o3-transfer-readiness. Author approved A after
the native PEM locking audit in 08-13-DISCOVERY.md. This is a technical byte
isolation increment, not a new PEM result or an adopted scientific stage.

## Guarantee and exact scope

`RetainedSnapshot` owns immutable byte buffers for every admitted member.
Consumers receive bytes or freshly parsed JSON copies; they cannot mutate the
stored evidence through that interface. Admission reads a complete pinned ZIP
blob into memory. It never extracts files, opens the live origins, executes
archived source, fetches data or invokes historical productive verifiers.
After admission, replacement/deletion of the archive or origin cannot change
the owned evidence. This guarantee assumes trusted verifier code in the process;
it is not a sandbox against arbitrary malicious Python code in that process.

Capture requires an external SHA256 pin on a sealed plan, and an expected SHA256
and byte length for every member. The plan is included byte-for-byte in the ZIP;
its external pin, internal seal and exact declared closure are checked again on
admission. Pinning a manifest label without including/checking that plan is not
sufficient. Every ZIP member must match the pinned plan, without extras,
duplicates, compression, links, encryption or extraction. Limits come from the
new versioned technical policy; they do not select scientific populations.

POSIX capture traverses all path components using descriptor-relative opens
with nofollow. It rejects special files, hardlinks, symlinks, unsafe names,
failure/lock/partial members, incorrect size/hash and observed metadata drift.
It repeats all origin reads against their expected hashes before packaging.
New archive publication uses exclusive-create and descriptor-relative nofollow,
outside every input root; never overwrites or removes incomplete outputs.
Existing directories must be supplied explicitly. Windows capture/publication
refuse; pure archive admission and verification are portable.

**Capture checks are observations, not writer exclusion.** No proof of an
atomic point-in-time historical capture or live/global producer quiescence is
claimed. The immutable snapshot itself supplies isolated consumption. The
externally pinned plan is a trust anchor, not an automatic scientific approval:
an independently supplied but scientifically wrong plan can pass byte checks.
Self-consistent bytes are not sufficient for parent population/measurement
correctness. Those checks belong to the subsequent stage-specific adapter.
Unselected failure/lock files and transient caches are not certified clean by
this declared-member-only gate. Original stage guards remain necessary.

## Separate interface

Policy: `config/dante_workflow_evidence_snapshot_v1.json`.
Module: `src/dante_workflow/evidence_snapshot.py`.
CLI: `scripts/dante_evidence_snapshot.py` (not registered as workflow PASS).

Plan shape:

```json
{
  "schema_version": 1,
  "status": "FROZEN_RETAINED_EVIDENCE_CAPTURE_PLAN_V1",
  "entries": [
    {
      "name": "logical/member.json",
      "root": "explicit_root_identifier",
      "relative_path": "member.json",
      "sha256": "EXPECTED_SHA256_FROM_THE_BOUND_INPUT_SPEC",
      "size_bytes": "EXACT_INTEGER_BYTE_LENGTH"
    }
  ],
  "plan_digest": "SHA256_OF_CANONICAL_BODY_WITHOUT_THIS_FIELD"
}
```

Entries are ordered by name, with unique casefolded names and root/path bindings.
The illustration uses explanatory strings; executable plans require integer
sizes and 64 lowercase hexadecimal digests. Seal canonicalization is UTF-8 JSON,
sorted keys and compact separators, without non-finite values. The external plan
pin is the SHA256 of its original bytes, not just its semantic seal.

For explicit POSIX paths and an independently pinned plan:

```text
python -B scripts/dante_evidence_snapshot.py capture --plan /absolute/plan.json --expected-plan-sha256 PLAN_FILE_SHA --root explicit_root_identifier=/absolute/input --output /absolute/new-output/snapshot.zip
python -B scripts/dante_evidence_snapshot.py verify --snapshot /absolute/new-output/snapshot.zip --expected-sha256 ARCHIVE_SHA --expected-plan-sha256 PLAN_FILE_SHA
```

No productive options exist in verify mode. Success emits only
`PASS_ISOLATED_SNAPSHOT_BYTES_ONLY_V1`, byte counts and binding hashes. No scores,
verdicts, target names or outcome counts are emitted. Scientific parent closure,
PEM replay, fresh sensor/null replay, full workflow verification, live writer
exclusion and historical modification are all explicitly false in the receipt.
The module/CLI/policy freeze is recorded separately in the 08-13 summary.

## Next gate

Bind the original frozen native PEM and explicit upstream scientific evidence to
this snapshot interface. Test complete parent/source closure, unchanged selection
and retained-calibration decision parity, missing/altered evidence refusal and
no live-origin dependence before historical replay. Do not call the old verifier
that can publish a compact. A byte-only PASS must not open scientific downstream
stages or justify a full multi-run/Virgo readiness claim. O3a diagnostic closure
and all historical scientific contracts remain unchanged.
