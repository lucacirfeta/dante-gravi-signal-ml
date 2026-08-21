# DANTE-Light O4b public auxiliary diagnostic

Status: **PASS, diagnostic only**.

The frozen analysis covers all 18 O4b DANTE-Light escalations (8 H1 and 10
L1) using five local detector/background epochs. The official GWOSC O4
auxiliary inventory contains 14 H1 and 11 L1 channels, but public availability
does not establish astrophysical safety. The endpoint therefore uses only the
published environmental monitors (one H1, two L1) and cannot veto, confirm, or
physically classify a candidate.

Each epoch contains 142--150 candidate-excluded CAT1 windows of 32 s from a
four-hour block. Off-diagonal window pairs calibrate the family-wise
max-over-channel time-shift null. Aligned quiet windows independently calibrate
the zero-lag null, controlling persistent coherence such as the 60 Hz mains
line. Bootstrap intervals resample window identities rather than dependent
pairs. The largest event-to-background separation is 27,333 s (7.59 h), below
the frozen 12 h fail-closed limit.

Results:

- 14/18 `NO_AUXILIARY_EXCESS`;
- 4/18 `PERSISTENT_BASELINE_COMPATIBLE` (one H1, three L1);
- 0/18 `AUXILIARY_EXCESS`;
- 0/18 unavailable.

The four baseline-compatible events exceed only their local time-shift
threshold. None exceeds the quiet zero-lag family-wise threshold. The strongest
event-level value is 0.994276 at L1 GPS 1414951104, at 60 Hz, below its local
zero-lag threshold 0.996859.

Interpretation is deliberately limited: no candidate-specific excess is seen
in the small public environmental witness set. This does **not** exclude an
instrumental origin, establish a new morphology, or support an astrophysical
origin. It demonstrates why raw or time-shift-only coherence is insufficient
when persistent detector lines dominate.

Machine-readable evidence is in `o4b_auxiliary/result_v1.json`; the fail-closed
gate is `scripts/verify_dante_light_o4b_auxiliary.py`.
