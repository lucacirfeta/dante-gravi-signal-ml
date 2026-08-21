#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 /path/to/python /path/to/aux-cache" >&2
  exit 2
fi

python_bin=$1
cache_dir=$2
runner=scripts/run_dante_light_o4b_auxiliary.py
output_dir=artifacts/dante_light/o4b_auxiliary

run_calibration() {
  detector=$1
  gps=$2
  "$python_bin" "$runner" \
    --detector "$detector" \
    --gps "$gps" \
    --block-seconds 14400 \
    --cache-dir "$cache_dir" \
    --output "$output_dir/calibration_${detector,,}_${gps}_v1.json"
}

run_calibration H1 1404598432
run_calibration H1 1409759680
run_calibration H1 1415053344
run_calibration L1 1409759744
run_calibration L1 1414942688
