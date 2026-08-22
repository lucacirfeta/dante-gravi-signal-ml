# DANTE-Light L4 prefilter: frozen tuning result

Date: 2026-08-22

Status: `NOT_READY`. Routing remains disabled. The held-out O4b shadow and
evaluation partitions were not opened by the tuner.

## Frozen inputs

- Protocol: `config/dante_light_prefilter_protocol_v1.json`
- Protocol digest:
  `b8a2a21ed933f116297425af2c60ff1b04480de2e0203e2f5d9017fbcb050a53`
- Tuning artefact:
  `artifacts/dante_light/prefilter_l4_v1/threshold_tuning_v1.json`
- Tuning artefact SHA256:
  `36d77d4bd3e2c668b633b6baaf8bd9fef7d8b6df7d3c2abb60666950f975aceb`
- Development population: 552 frozen background windows, 40 robust
  candidates, 72 known glitches separated by detector and morphology, and 210
  CBC injections separated by detector and source system.

The result was reproduced twice byte-for-byte, once in the external working
cache and once in the repository artefact path. Feature-ledger and row hashes
are embedded in the tuning artefact.

## Result

The best outcome-blind OR operating point satisfying at least 90% development
retention in every detector/morphology group was:

- crest-factor threshold: `4.281442138656343`;
- peak-band-fraction threshold: `0.012430641922920281`;
- background windows selected before audit: 514/552;
- rejected windows sampled by the deterministic audit: 1/38;
- effective expensive-call count: 515/552;
- effective compute reduction: `0.06702898550724634` (6.70%);
- frozen required compute reduction: 50%.

The active retention boundary is not one anomalous cohort: three injection
groups retain 32/35, two H1 known-glitch groups retain 11/12, and the H1 robust
group retains 19/20. Therefore the simple two-feature OR rule has substantial
overlap between background and every required positive-control family. The
5% audit is not the cause of failure: reduction before audit is only 6.88%.

## Scientific boundary

No threshold or gate may now be relaxed using this observed outcome. Assembly
correctly refuses a `NOT_READY` tuning artefact, so no evaluation contract or
claim of compute savings has been produced.

The defensible choices are:

1. close L4 v1 as a negative result and retain the exact DANTE-Light path;
2. define a new prefilter representation or model under a new, prospectively
   frozen protocol and repeat development/held-out validation from the start.

Changing the 50% reduction target, the 90% per-group retention target, the
control populations, or the feature rule after seeing this result would be a
scientific protocol change and requires an explicit decision before coding.
