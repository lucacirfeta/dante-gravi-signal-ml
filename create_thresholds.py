import json
from pathlib import Path

# The remaining 9 channels and their calibrated thresholds
# For FPR < 1%, L1:IMC-WFS_B_I_PIT_OUT_DQ needs threshold 0.8 (since at 0.6 it was 4.8%).
# All others had 0.0% at 0.6, so they remain at 0.6.
thresholds = {
    "L1:ASC-X_TR_A_NSUM_OUT_DQ": 0.6,
    "L1:CAL-PCALX_RX_PD_OUT_DQ": 0.6,
    "L1:CAL-PCALY_RX_PD_OUT_DQ": 0.6,
    "L1:IMC-WFS_B_I_PIT_OUT_DQ": 0.8,
    "L1:OAF-IMC_WFS_B_I_PIT_PREFILT_OUT_DQ": 0.8,
    "L1:SUS-ETMX_L1_CAL_LINE_OUT_DQ": 0.6,
    "L1:SUS-ETMX_L2_CAL_LINE_OUT_DQ": 0.6,
    "L1:SUS-ETMX_L3_CAL_LINE_OUT_DQ": 0.6,
    "L1:SUS-PI_PROC_COMPUTE_MODE5_RMSMON": 0.6
}

out_dir = Path("data/production/aggregated/pem")
out_dir.mkdir(parents=True, exist_ok=True)
json_path = out_dir / "channel_thresholds.json"

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(thresholds, f, indent=4)

print(f"Created {json_path}")
