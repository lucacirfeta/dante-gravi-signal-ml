# O3a/O4a common-five-channel PEM: background source preflight

Status: **public-source coverage and frozen-span selector PASS; no paired PEM measurement or outcome opened**.

The read-only preflight used the frozen 12 O3a and 65 corrected-O4a target ledgers, their full run-specific candidate-exclusion populations, the historical null span receipts only as transport-planning inputs, and the unchanged historical span selector as an independent check. It reproduced all 77 exact four-hour span choices and clean-window counts. The complete public H1/L1 checksum manifests cover every selected span without gaps. O3a's manifest also lists Virgo frames; these are validated as manifest rows and excluded from this H1/L1 comparison.

| Run | Targets / selector replays | Frame uses | Unique official frames | Manifest SHA-256 |
| --- | ---: | ---: | ---: | --- |
| O3a | 12 / 12 | 57 | 47 | `9646ed9db6663f7b136878512f1d376cb0b0605aa1bd7f7112e7aa11d9e4ca03` |
| O4a | 65 / 65 | 295 | 278 | `531912260ea45cd5265198f7a1990a8a89f69ffa98abca8a21930140e332b7ba` |

These are frame-coverage counts, **not** PEM candidate or verdict counts. The source binding is `config/dante_o3a_o4a_common_pem_background_v1.json` (contract digest `c974bfb7ee83ad699bf01c2543075de27f38a772c8b76ebea775e0ec25f53fd7`). It pins the public manifest bytes, release, sampling geometry, calibration metadata and parent contracts. O3a frame/channel identities follow [GWOSC O3 technical details](https://gwosc.org/O3/o3_details/); the corrected-O4a identities are additionally cross-checked against the frozen O4a raw-replay source contract. The actual HDF5 metadata and published MD5 must still be checked for **each acquired frame**; a documentation match alone is not a frame-byte verification.

The draft `OfficialBackgroundReader` checks published MD5, detector, frame type, strain channel, GPS interval, sample rate, float64 geometry, finite values and assembled numerical SHA-256. A separate replay routine rereads existing frame bytes and independently recomputes the span hash, refusing changed file/receipt identity. Synthetic tamper tests pass. No full background frame acquisition or independent replay of 77 real spans has happened yet.

A parity-relevant guard was corrected before any new measurement: O3a's historical H1 PEM cache contains 512 Hz SUS calibration-line auxiliary channels. The original draft incorrectly required every event auxiliary to support the 500 Hz analysis-band ceiling and would have silently excluded these channels. The wrapper now requires complete, finite coverage at each channel's own positive sample rate and leaves the historical core's channel-specific Nyquist restriction intact. Both event and background auxiliary coverage are checked; tests prove that 512 Hz is accepted and a partial span is rejected. This is preservation of the frozen method, not a retuning.

Verification so far: 68 combined common-PEM/O3a/O4a provenance tests passed, 11 upstream GWPy/Matplotlib warnings; Ruff check and format passed. The live source-bound coverage preflight exited 0 with the counts above. Gate 3 remains **open**: real frame bytes, complete auxiliary receipts, source freeze of the paired runner, deterministic independent outcome replay and the unchanged historical-artifact audit are pending. Neither an O3a nor an O4a comparative PEM verdict may be interpreted before those gates pass.
