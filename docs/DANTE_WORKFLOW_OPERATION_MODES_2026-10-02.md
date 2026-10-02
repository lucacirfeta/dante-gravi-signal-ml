# Common workflow: retained verification versus new execution

Date: 2026-10-02. Internal administrative boundary, not all-run certification.
The O3a diagnostic study remains closed. No scientific contract is changed.

## Implemented boundary

The existing workflow schema 2 can now refer to a graph-profile schema 2 with
an explicit `operation_policy`. Graph-profile schema 1 and workflow schema 1
keep their previous field sets and behaviour. The new policy is protected by
both the profile's canonical seal and its externally referenced file SHA.

- `EXECUTE_AND_VERIFY`: existing command/run/adoption semantics. Its
  `stage_receipts` mapping must be empty; it confers no additional scientific
  applicability or new adapter registration.
- `VERIFY_RETAINED_ONLY`: every graph stage has a pinned receipt policy with
  exact `status`, `verification_level` and `seal_field` (`receipt_digest` or
  `artifact_digest`). Each stage must also produce a scoped wrapper output.
  The adapter must explicitly opt in after read-only source audit; existing
  O3a/O4a adapters do not opt in and are not silently made read-only.

Only verifier commands are constructed for a retained profile; the controller
checks their frozen prefixes before opening a ledger. There are no dummy run
commands, no `run` mapped to `verify`, and no O4a fallback. CLI run/resume,
repair and scientific preflight are refused before lease/process execution.
UI Start/Resume/preflight are disabled and server-side guarded before launch.
Administrative orchestration may write its own new ledger/logs/receipts; this
is not a claim of globally read-only filesystem behaviour.

Adoption admits a stage only after OS exit 0, strict finite/unique-key JSON,
exact scoped PASS/verification level, `full_workflow_verified:false` and a
correct canonical receipt seal. Hash-bound logs retain the complete verifier
output; compact aggregate evidence carries only identity/scope, not outcomes.
Standalone workflow verification rechecks those logs and reruns each verifier:
the new sealed evidence must exactly match the admitted receipt digest/scope.
All existing graph dependencies and exact COHORT/INDEX manifest equality stay.

The retained aggregate status is
`PASS_VERIFIED_RETAINED_WORKFLOW_EVIDENCE`, not `PASS_VERIFIED_WORKFLOW`.
Its boundary explicitly states retained evidence only, no new scientific run,
and `full_workflow_verified:false`. Report generation and stored-report serving
respect this scope; changing a retained receipt's status to the full PASS label
is rejected even if its self seal is recomputed. A self seal alone is not an
external trust anchor or an independent scientific/source acquisition.

## Verification and limitations

The temporary synthetic fixtures exercise the same common engine with O3a and
O4a administrative labels, mocked verifier subprocesses and a fixed immutable
input ledger. They are not production graphs, numerical replay or scientific
approval of either observing run. Existing production configs/registry/adapter
factory remain unchanged, and unsupported profiles stay blocked.

Initial focused Windows suite: 28 PASS. First broader Windows attempt: 201 PASS,
2 failures in CLI test doubles without the new specification field. The test
doubles were explicitly given legacy `retained_only:false`; their stop/failure
expectations were not weakened. Native Python lacks Ruff; no dependency was
installed. WSL Ruff is used instead. A command selector initially named two
nonexistent UI paths while reading source; corrected without touching data.

Final verification counts and source checkpoint are recorded in 08-22-SUMMARY
and 08-22-VERIFICATION. No real scientific runner, historical verifier or reader,
raw/NDS2 fetch, scoring, thresholds, null, outcome review, GPU change, push,
main merge or public release was performed for this increment.

## Next increment

Build the common, profile-specific exact-GPS input/preflight contract boundary
and test operator wiring, then perform clean-install bounded numerical replay
for an individually approved productive profile. Retained receipt translation
into real adapters and public registration require their own tested frozen
input mappings; this generic policy does not complete that mapping. Other runs
and V1 still require their scientific profile qualification. Availability of
data or a catalogue entry is not execution readiness.
