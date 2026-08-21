# DANTE-Light O4b frozen escalation follow-up

Run date: 2026-08-21. This note summarizes machine-readable artifacts under
`artifacts/dante_light/o4b_followup/`; it does not replace their hashes or the
fail-closed verifier.

## Cohort and provenance

- The canonical and shared prospective records reproduce the same frozen
  cohort: 18 `ESCALATE` windows out of 768, comprising 8 H1 and 10 L1 windows.
- Every detector/GPS identity, score, threshold, strain digest, image digest,
  and Top-k localization record agrees between the paired shadow engines.
- The follow-up manifest SHA256 is
  `ec08a37e19f8987d98a4e1c7cb65ad9a73d104643578c89806a1d15976ae5b0b`.
- `ROBUST` in the ledger means only that the frozen native DSD score exceeds
  the causal detector-specific O4a upper threshold. It does not mean novel,
  instrumental, astrophysical, or physically coincident.

## Physical coincidence

- All 18 windows are accounted for. Four L1 windows have no valid H1 partner
  context and are explicitly `PARTNER_DATA_UNAVAILABLE`; the GWOSC
  `H1_CBC_CAT1` timeline has no whole-context coverage for any of the four,
  while the candidate L1 data remain valid.
- Fourteen windows have finite physical cross-detector measurements and 95
  valid time-shift null values in total.
- Two of the fourteen have `cc_onsource` marginally above their own small
  per-event null maximum:
  - H1 GPS 1409757632: 0.07540 versus 0.07187 from 7 null shifts;
  - L1 GPS 1409759744: 0.08837 versus 0.08672 from 5 null shifts.
- Neither crosses the pooled-null p99 diagnostic, 0.21295; the largest
  on-source coefficient in the measured cohort is 0.11896.

These are descriptive checks. The per-event nulls have only 5--8 usable shifts,
and the pooled p99 was not pre-registered as an O4b population threshold.
Accordingly, this follow-up does **not** claim a physical coincidence for either
window and does not reinterpret the locked shadow endpoint.

## Catalog and morphology audit

- A byte-preserved snapshot of the official public GWTC-5.0 API contains 161
  O4b events. None has a catalog GPS inside any of the 18 frozen 32 s windows.
  This excludes a match to a listed GWTC-5.0 event; it does not establish a new
  glitch morphology.
- The canonical Q-transform gallery regenerates all 18 strain and image hashes
  exactly. White boxes show the stored Top-k patches and the red line their
  median time localization. Several windows contain multiple structures, so
  the localized novelty region need not be the visually brightest feature.
- No released O4b Gravity Spy label has been assigned here. Visual appearance
  alone is not used as a supervised morphology label.

## Reproducibility

Run:

```text
python scripts/build_dante_light_o4b_followup.py manifest
python scripts/build_dante_light_o4b_followup.py physical --device cuda
python scripts/build_dante_light_o4b_followup.py catalog
python scripts/snapshot_dante_light_o4b_partner_availability.py
python scripts/build_dante_light_o4b_followup.py gallery
python scripts/verify_dante_light_o4b_followup.py --stage all
```

The final verifier requires exact cohort/source/implementation hashes, complete
per-window accounting, finite null ledgers, frozen GWTC bytes, CAT1 evidence for
unavailable partners, and 18/18 exact image regeneration.

## Remaining scientific boundary

The next evidence layer is an explicitly open-set morphology comparison against
held-out labelled controls, followed by selected-site PEM checks where public
auxiliary channels exist. Neither layer may retroactively alter the shadow
manifest or detector thresholds. Human/instrument-scientist review remains
necessary before any candidate is described as a new instrumental class.
