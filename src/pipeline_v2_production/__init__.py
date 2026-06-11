# src/pipeline_v2_production/__init__.py
"""
Pipeline V2 Production: Rigid O4a Patch-Level MIL Engine.
Operates strictly on 384-dimensional L2-normalized patch token geometry.

Modules:
    - production_cluster: DPMM clustering on 384D MIL manifold
    - production_report: Per-session Markdown report generator with saliency galleries
    - aggregate_report: Cross-session deduplicator and Spearman rank correlation reducer
    - production_writer: SWMR-enabled HDF5 novelty archive writer
    - saliency_map: Three-panel topological saliency map generator
"""
