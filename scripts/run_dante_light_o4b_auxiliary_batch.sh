#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 /path/to/python /path/to/aux-cache" >&2
  exit 2
fi

python_bin=$1
cache_dir=$2
runner=scripts/run_dante_light_o4b_auxiliary.py
output_dir=artifacts/dante_light/o4b_auxiliary/events
mkdir -p "$output_dir"

run_group() {
  detector=$1
  calibration=$2
  shift 2
  for gps in "$@"; do
    "$python_bin" "$runner" \
      --detector "$detector" \
      --gps "$gps" \
      --cache-dir "$cache_dir" \
      --calibration-from "$calibration" \
      --output "$output_dir/${detector}_${gps}_v1.json"
  done
}

run_group H1 artifacts/dante_light/o4b_auxiliary/calibration_h1_1404598432_v1.json \
  1404598432
run_group H1 artifacts/dante_light/o4b_auxiliary/calibration_h1_1409759680_v1.json \
  1409757632 1409759680 1409760064
run_group H1 artifacts/dante_light/o4b_auxiliary/calibration_h1_1415053344_v1.json \
  1415052192 1415052224 1415053344 1415054816
run_group L1 artifacts/dante_light/o4b_auxiliary/calibration_l1_1409759744_v1.json \
  1409756544 1409757504 1409759680 1409759712 1409759744 1409759904
run_group L1 artifacts/dante_light/o4b_auxiliary/calibration_l1_1414942688_v1.json \
  1414941408 1414942688 1414942880 1414951104
