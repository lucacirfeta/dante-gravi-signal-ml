# src/core/__init__.py
"""
Core shared primitives and data-loading foundations for the gravi-signal-ml pipeline.
This package contains hardware-agnostic utilities, data loaders, signal preprocessing,
DINOv2 encoder, and patch-level feature extraction primitives.

INVARIANT: This package MUST NOT import from pipeline_v1_legacy or pipeline_v2_production.
"""
