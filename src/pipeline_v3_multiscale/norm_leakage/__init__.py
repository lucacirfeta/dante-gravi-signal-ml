"""Norm-leakage factorial experiment (Fase 2 audit).

Question: do VQ dictionary centroids encode a run-specific signature via
the per-image min-max normalization (contrast coupling driven by the
image max statistic), independently of temporal proximity?

Design: 2x2 factorial — dictionary run (O3a / O4a) x normalization scheme
(B1 = per-image min-max, B2 = fixed run-independent clip). The statistic
of interest is the INTERACTION: does the cross-run score gap shrink under
B2? Pre-registered criteria live in analyze.py and must not be edited
after looking at the data.
"""
