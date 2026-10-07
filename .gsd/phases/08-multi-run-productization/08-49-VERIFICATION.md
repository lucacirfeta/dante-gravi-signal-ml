# Synthetic CW Stage A implementation verification

## Approved scope

The latest author `procedi` approves the full3280-context package in546d07d:
16 independent synthetic noises, 2880 singleton injections,16 baselines and
384 two-tone probes. This is not a detector population or equivalence test.
The versioned config is `config/dante_cw_stage_a_v1.json`.

## Observed pre run evidence

WSL Ubuntu, `/home/atafe/miniconda/envs/dante_env/bin/python`:101passed,
14upstream warnings,16.51s, actual OSexit0 and `TEST_EXIT_CODE=0`, session84525.
Suite: new StageA tests plus PatchProducer context/axis and normalization
regressions. The normalization regression includes an existing cached encoder
fixture; this is not part of the StageA measurement route. New synthetic
fixture uses an actual spawned process and produces exact uint8RGB equality
against inherited `_worker_preprocess`, including the1991Hz edge probe.

Final test log:
`C:/Users/atafe/PycharmProjects/dante-gravi-signal-ml/.gsd/evidence/cw_stage_a_20261007/pytest.freeze.log`.
Supervisor log at the same path records actual test exit0. Earlier first
iteration:97passed in15.05s, actual terminal OSexit0, but its Bash exit marker
was empty; do not use that marker as proof. Final invocation corrects capture.
First Ruff check found E731 in a new reporting helper, corrected before
freeze. Final Ruff check on module/CLI/tests: all checks passed, OSexit0.
The intermediate99passed suite is retained in pytest.final.log; the final
101passed suite adds durable supervisor observed-exit and duplicate refusal
fixtures. The supervisor launches exactly one controller, records its actual
OS exit and never starts another stage.

Pre-launch rawSHA freeze:
- config2124e321d5f40b068d022d48b021a0ea22cd70d88e4a48e8a30fd292abe2347e
- modulee825c833b7864beb1e6497fcf71abe31543810b32978265e5f10a35dfc041e4d
- CLI70911b28b1ff979272dd964faf72086dbeb6fbaa6f919eaf6d728a2156b52c2d

Fixtures cover all18frequencies/two phases, all5doses, one-sided synthesis
normalization/Parseval, deterministic independent child streams, low PSD
extension, band-bin overlaps, invalid denominator rejection, negative response,
uint8overflow prevention, source/config guards, incomplete input, spawned exact
production fixture and administrative receipt/metric/tampering boundaries.
Floating fixture tolerances are numerical arithmetic checks, never scientific
acceptance/equivalence margins.

## Scientific primitives and observables

Inherited preprocessor/utils/data_loader/PatchProducer/config.yaml rawSHA
pins are in the isolated contract; none changed. Installed runtime exact:
NumPy2.4.6/SciPy1.17.1/GWpy4.0.1/LALSuite7.26.15/Matplotlib3.11.0/Astropy8.0.0.
Runtime manifest records whitening/filter signatures and actual ZPK coefficients
(bandpass order10), not the inaccurate historical Butterworth docstring.
Every arm recomputes inherited context ASD/whitening before crop and Q-transform.
ObservedTimeSeries captures the Q object returned by the very same inherited
generate_qtransform call; no second Q scientific algorithm or fixed native grid.
Native Q axes are time then frequency. Resized coordinates use the inherited
order1 zoom geometry and remain image coordinates, not independent spectral bins.

Known synthesis PSD band integral uses scaled SciPyquad with its installed
defaults and retains numerical quadrature error. Dose is constructed with the
approved tone-only32s Hann periodogram and bin-width overlap. Absolute signed
spectral excess and noise-relative E/G remain separate from min-max RGB response.
Pairs retain component bands; overlapping bands are not independent measures.
Native/full resized Q frequency profiles and full temporal PSDs are retained.

Frequency values checked against the official
[T2500198v3 start-frequency column](https://dcc.ligo.org/public/0200/T2500198/003/O4_injection_params.html).
The noise benchmark is the approved
[LALSimulation design model](https://lscsoft.docs.ligo.org/lalsuite/7.26/lalsimulation/group___l_a_l_sim_noise_p_s_d__c.html),
not measuredL1/O4b noise. The diagnostic density estimator follows
[SciPy periodogram](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.signal.periodogram.html).

## Execution boundary

Implementation verification only; complete run not yet claimed here.
One fresh ext4 run follows source freeze. All-artifact read-only validation
checks hashes, identity/count, finiteness and reconstructs metrics from retained
arrays; it explicitly does NOT repeat numerical preprocessing or certify CW
equivalence. No real-strain/DINO/index/threshold/flags/StageB/O4b route.
No automatic next scientific stage, old verifier retry or scheduled monitor.
