#!/usr/bin/env bash
# Chained overnight batch: finish the DSD-rejected (BACKGROUND) PEM measurement.
#
# The coherence step rewrites coherence_report.csv from scratch, so the 63
# events already measured must be merged back before calibrating -- otherwise
# apply_family_wise_verdicts, which iterates that CSV, silently drops them even
# though their calibration JSONs are still on disk.
#
# Steps: wait for coherence -> merge with the pre-run backup -> calibrate the
# new events (existing JSONs are skipped) -> regenerate tiered verdicts.
set -u
cd /mnt/c/Users/atafe/PycharmProjects/dante-gravi-signal-ml || exit 1
PY=~/miniconda/envs/dante_env/bin/python
PEM=data/production/aggregated/pem
BACKUP=data/production/aggregated/pem_backup_2026-07-24_pre_bg

echo "[$(date)] waiting for the coherence step to finish"
# The bracket makes the pattern not match this script's own command line.
# Without it, any waiter whose command line contains the literal pattern -- this
# one, or a separate monitor started with the same string -- matches itself or
# the other, and both spin forever on work that already finished.
while pgrep -f '[p]em-coherence-analysis' >/dev/null; do sleep 60; done
echo "[$(date)] coherence finished"

echo "[$(date)] merging with the 63 events measured before this run"
$PY - <<'EOF'
import pandas as pd
from pathlib import Path
pem = Path("data/production/aggregated/pem")
backup = Path("data/production/aggregated/pem_backup_2026-07-24_pre_bg")
new = pd.read_csv(pem / "coherence_report.csv")
old = pd.read_csv(backup / "coherence_report.csv")
key = ["detector", "gps_start", "aux_channel"]
have = set(map(tuple, new[key].itertuples(index=False, name=None)))
missing = old[~old[key].apply(tuple, axis=1).isin(have)]
merged = pd.concat([new, missing], ignore_index=True).sort_values(
    ["detector", "gps_start", "aux_channel"])
merged.to_csv(pem / "coherence_report.csv", index=False)
print(f"merged: {len(new)} new + {len(missing)} restored = {len(merged)} rows, "
      f"{merged.groupby(['detector','gps_start']).ngroups} events")
EOF

echo "[$(date)] calibrating the family-wise null for the new events"
$PY -m src.pipeline_v2_production.pem_null_calibration --run O4a
echo "[$(date)] batch complete"
