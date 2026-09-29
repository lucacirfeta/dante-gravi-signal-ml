# O3a/O4a common-PEM auxiliary input binding — 2026-09-29

This is a transport-only increment of execution gate 3 in `07-20-PLAN.md`.
It does **not** evaluate the five-channel null, a PEM verdict, a candidate,
or global significance.

The new versioned binding contract pins the previously verified 750-series
native-sample run key and its sealed summary digest. The read-only
`VerifiedAuxiliaryReader` accepts only an exact frozen run/detector/target,
five detector-local channels, and each of that target's event and background
intervals. Before returning a GWPy time series it checks the parent plan,
summary, source hashes, exact receipt and NPY byte/numerical hashes, native
rate, finite samples, and unit. A missing or changed source fails closed;
there is no NDS2 fallback or second source acquisition.

The public comparative measurement entry point now constructs this reader
itself. Its injected fetch is scoped over the unchanged historical event
coherence and background-null functions. In particular, historical
background resampling and the window-index block bootstrap remain in their
original core; this adapter changes only where the frozen auxiliary input
bytes are read. The core's old NDS2-oriented log line may still say
"Fetching ... from NDS2" even though the patched transport is local; that
line is not evidence of a new NDS2 request.

Read-only real-source checks exited 0: one sealed O3a auxiliary sample was
loaded at its recorded native float32 rate, and all 77 target contexts
resolved to exactly five event plus five background channel/interval uses.
No PEM outcome was opened. The WSL O3a/O4a common-PEM, native-PEM and
PatchProducer regression returned 99 PASS, 11 GWPy/matplotlib upstream
deprecation warnings. Ruff lint and format passed.

Still required before any paired PEM result: complete event/background strain
reader wiring, independent CAT1/target/exclusion and historical-artifact
checks in the productive runner, synthetic deterministic-replay tests, source
freeze, and then separate O3a/O4a runs and verifiers. The prior O3a-only PEM
diagnostic remains unchanged. A five-channel no-correlation result would not
clear channels absent from the public common subset.
