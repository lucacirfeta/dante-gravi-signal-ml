# 08.35: exact expanded calibration context consumer

## Scope and authority

Author `procedi` resumes the announced provider increment after08.34. The new
provider is an explicit opt-in consumer, NOT productive promotion. It connects
the approved expanded native admission to the same CompleteContext interface
used by the previous exact admitted reader. The old production profile,
28-context admission, workflow factory and default runners are unchanged.
No population, sample geometry, DQ, preprocessing, scoring or validation rule is
chosen here. All scientific parameters come from the pinned parent protocol.
In particular, this stage does not invent a full-context DQ acceptance criterion.

The implementation binds all39971 calibration identities (19715H1+20256L1) to
39891 unique padded native contexts:39863 new containers plus28 prior references.
Metadata identities may share a context; they are not deduplicated out of the
scientific population. New and prior context keys must form the complete,
disjoint frozen union; unknown detector/interval requests fail, never fall back.

Per-read checks reuse `AdmittedContextProvider.read`: exact native grid, dtype,
finite samples, container SHA and historical numerical SHA. The consumer also
checks the retained context receipt, historical series name and source/contract
pins. Source labels preserve the legacy16KHZ string; they do NOT claim16kHz
native sampling. No whitening, Q-transform, model or score is executed here.
Active lock/failure evidence blocks reads; initial binding rejects partial/tmp.
This is not a writer-exclusion certificate.

## Freeze and input pins

Source freeze `f9f62493e16d60f8ec4d9928c1dfe49b56d38e04`.
Contract `config/dante_workflow_expanded_context_provider_v1.json`, SHA
`42a8927251b81134dcfda479630ad1678421166650a3205c4b8669fff919535c`.
Parent policy remains SHA
`102c7f9e5050a81c0e28d3a50b2f9ce4b2c30b5ee31427fba60767f672eef622`.
All four evidence pins are versioned in the new contract, not inferred from chat.
08.34 admission/plan/summary/verification and its17 sources remain unchanged.

External recovery input:
`E:\dante_cache\dante_workflow\calibration_expanded_admission_20261003\prepared_v1\recovery`.
New output only:
`E:\dante_cache\dante_workflow\expanded_context_provider_20261004`.

## Observed checks

WSL synthetic and regression suite:211 PASS,11 upstream warnings,14.52s, OSexit0;
46 tests belong to the new consumer suite. Ruff lint and format PASS for3 new
source/script/test files. Five source hashes plus contract bytes match Git freeze.

Preflight67604 observed OSexit0, empty stderr,
`PASS_EXPANDED_CONTEXT_CONSUMER_BINDING_ONLY`,39971 identities/39891 contexts.
Evidence seal `321217569131d92f18f95c6c0fc985d637e1ac59543d53647c4782c0124225cb`,
SHA `6731ced30a0adf17f3054932c7be343da624539640feda3b30e3bb96f9daa9b4`.
Standalone binding verifier84901 observed OSexit0/`BINDING_VERIFY_EXIT=0`, the
same seal/counts and identical expected report; both stderr logs empty. Evidence
fileSHA remained unchanged. This closes the bounded input-consumer binding gate.
No08.34 transport, full-domain raw verifier or admission was repeated.

The preflight checks sealed evidence relationships, metadata completeness and
the preserved prior provider. It does NOT read every new context through the
new consumer: `all_expanded_contexts_read_through_consumer=false`. The standalone
binding replay is not an independent full-domain numerical replay or a second
GWOSC fetch. Synthetic HDF5 reads verify the reader logic, not all real inputs.

An early negative test appended only JSON whitespace to a sealed context receipt;
that does not change the canonical seal. The test was corrected to corrupt its
content; no receipt validation rule was weakened and no historical file edited.

## Explicit remaining gates

Next: source-frozen full-domain consumer numerical replay and full-context
preprocessing/validity evidence, then isolated fresh calibration measurement and
independent verifier with unchanged historical replay/p99 gates. Any genuinely
new scientific/structural choice still requires the author before implementation.
No productive promotion, candidate scan, O4b, all-run scientific certification,
push/main or additional shutdown is authorized by this increment. O3a remains
closed; user untracked output/public_smoke files are preserved. Monitor stays paused.
