# O3a native index: technical PASS, scientific interpretation pending

The 2026-09-23 index run
`8b6d6cc706973bc512a9c1f76f9693c232d2c8161e47a285d563b7b3ab351e75`
completed and passed `scripts/run_dante_o3a_native_index.py --verify` in the
canonical WSL/CUDA runtime. It used only the frozen O3a cohort, not O4a
scientific rows. There was no failure artifact. The verifier checked all
1,294 token shards and replay rows, exact clean/raw-context hashes, 1,771,486
tokens, the 1,216-by-384 index, the 50,000-by-384 raw sample, finite/L2 gates,
and output file hashes. The focused WSL suite had 87 passing tests.

Evidence:

- Contract digest: `f8ca604dd15e0e899b155c89007eb0d297146d3a21eb7b4bba29338518f5a0dc`
- Cohort artifact digest: `709c6fc5c3a22c89c21cd92303de2acf4d5ab1e30a016ddaaa89ebaf69daf382`
- Index artifact digest: `8ce38ae0ee85a2c45c01b592daab29a9beca52fa735815f1519c0603806041f0`
- Index SHA-256: `79d44c710fbf8760c044ee21cf0d68f0694be13086a9de934fa7a87d66410cae`
- Replay ledger SHA-256: `2a906dea85e4dad8cecd27974aebc1f52b43b0847388477d38bbfb0213530b9c`
- External summary SHA-256: `99c39ba37fda6996df695a1ddd18620a41bda53062129e8df68bdb50031e6033`

The completed run is **not yet adopted for downstream science**. During the
run, GWPy 4.0.1 consistently warned that its Q tiling lowers the requested
20-2,048 Hz frequency range to 20-1,291.0530521679268 Hz for 4,096 Hz data
and `qrange=(4,64)`. A direct `QTiling(32, 4096, ...)` check confirmed this;
the identical request at 16,384 Hz (O4a sample rate) retained 2,048 Hz. O3a
initial calibration/scan also requested 20-2,048 Hz on 4,096 Hz data, so this
is likely a shared O3a effective-band issue, not isolated to index fitting.
It does not invalidate the technical replay but limits a claim of identical
effective representation between O3a and O4a. The NPZ metadata currently
records the requested frequency range, not the effective one.

Decision required before native calibration: either retain the 4 kHz O3a
pipeline and explicitly document/freeze its narrower effective support as a
cross-run comparability limit, or require matched effective support (which
would need a separately scoped source/representation change and upstream
recomputation). No downstream stage was opened or parameter changed here.
