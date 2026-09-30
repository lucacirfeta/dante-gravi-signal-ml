# Gate C implementation review: preprocessing semantics

## Author resolution (2026-09-30, before implementation/outcomes)

Both proposed policies below are now approved: relative ceil/ceil half-open
sample selection, and historical native-rate strain-only highpass followed by
antialiased resampling of all streams and exact local crop. The separate
`config/dante_o3a_l1_local_measurement_v1.json` records the methodological-parity
rationale and four historical source symbols with file hashes. This is not
case-specific optimization. Highpass alone is not an antialias filter; the
resampler supplies alias rejection. The original Gate B file remains unchanged.
The earlier blocked review is retained below as decision history.

Status: BLOCKED_BEFORE_IMPLEMENTATION pending two author decisions. No real
localized coherence, reference-tail score, bootstrap or new outcome was
computed. The input gate remains PASS_VERIFIED; all historical contracts,
receipts, sample files and the paused monitor remain unchanged.

## Evidence from primary code and approved contract

The approved local design in `config/dante_o3a_l1_local_followup_v1.json`
freezes the one-second continuous offset interval, 512 Hz analysis rate,
local Welch statistic and decision rule. It describes preprocessing as
`ANTIALIASED_RESAMPLE_AND_PARENT_20HZ_HIGHPASS_ON_FULL_32S_CONTEXT_BEFORE_LOCAL_CROP`.
It does not state discrete sample boundary rounding, which streams receive
the parent highpass, or the order of highpass and antialiased resampling.
The synthetic local kernel deliberately takes already preprocessed arrays;
it does not resolve these missing choices.

The installed WSL GWPy `TimeSeries.crop` implementation is state dependent:
without an explicit x-index it floors both bounds; with an x-index it uses
`searchsorted(..., side="left")`. For a fractional offset at 512 Hz these
select adjacent, shifted sets of 512 samples. The difference is at most
one sample (1/512 second), but may change the local Welch statistic. Do not
let incidental x-index creation decide the scientific interval.

The historical common-PEM code is asymmetric in preprocessing:
`src/dante_light/o3a_native_pem.py:_event_strain` applies the parent highpass
to strain at its native rate before returning it; the common measurement
passes native auxiliary samples into `calculate_coherence_and_plot` without
adding a highpass. That historical core then antialias-resamples faster
series to the pair's shared rate. The new local rate is already approved
at 512 Hz, but the shorthand "parent highpass" does not imply filtering
every auxiliary stream or reversing the parent order.

## Decisions proposed before any real measurement

1. **Discrete region:** recommend explicit relative-index, half-open
   selection `[ceil(offset_start * fs), ceil(offset_end * fs))`, using only
   the frozen relative offsets, never a large-GPS floating subtraction or
   GWPy crop defaults. This retains samples whose timestamps actually lie
   in the continuous interval. Record selected indices/timestamps in the
   execution receipt and apply identically to event and every control.
   Alternative: explicitly floor both bounds to preserve the historical
   crop convention when no x-index is materialized. Neither is currently
   named in the local contract.
2. **Full-context filtering:** recommend preserving the actual parent
   pattern: highpass **strain only**, at native rate, with the inherited
   parent cutoff/implementation, then antialias-resample strain and every
   auxiliary to the approved analysis rate; auxiliaries receive no new
   highpass. All preprocessing is on each full context before local crop.
   Alternative: explicitly define a new common highpass for strain and
   all auxiliaries after resampling. That is not historical parent parity
   and must be approved as an additional method choice.

These are proposed choices, not silently implemented defaults. The author
must confirm them before a separate versioned Gate C execution contract can
bind the already approved method, exact verified input receipt and explicit
sample/preprocessing policies. The frozen Gate B contract must not be edited
in place or invalidate its historical input plan.

## Other boundaries

Keep both target identities and multiplicity family two; first target stays
INCONCLUSIVE. Keep all metadata-approved blocks, exact five L1 channels,
conservative ties and the approved decision cutoff. Do not compare this
new reference screen to intra/cross-detector thresholds. Bootstrap remains
whole-block and descriptive; save the approved replicate distribution
without inventing a confidence level or changing the point decision.
No new channels, control selection, lag/band/time search, formal p-value,
sensor veto safety claim, physical attribution or external communication.

## Plan checker result

ISSUES_FOUND before execution. Requirement coverage is blocked by the two
unfixed numerical policies above. The next implementation can be bounded
to two tasks (adapter plus synthetic/independent-verifier tests; then source
freeze and real replay), with explicit input-receipt binding and completion
criteria. Dependencies on the verified matched-input gate are satisfied.
No productive output or new contract was opened; no code/config was changed.
The statistical/LIGO review follows the repository stop-and-ask rule rather
than selecting a method from runtime library defaults.
