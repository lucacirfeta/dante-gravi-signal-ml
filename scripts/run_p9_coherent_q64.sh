#!/usr/bin/env bash
set -euo pipefail

repo=/mnt/c/Users/atafe/PycharmProjects/dante-gravi-signal-ml
python_bin=/home/atafe/miniconda/envs/dante_env/bin/python

cd "$repo"
"$python_bin" -u -m src.pipeline_v2_production.astrophysical_injection \
  --run O4a \
  --pilot \
  --seed 42
"$python_bin" -u -m src.pipeline_v2_production.astrophysical_injection \
  --run O4a \
  --n-trials 25 \
  --seed 42
