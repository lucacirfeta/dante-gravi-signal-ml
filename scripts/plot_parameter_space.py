import numpy as np
import matplotlib.pyplot as plt
import os

# Ensure directory exists
os.makedirs("paper_draft/v5_15072026_arvix/img", exist_ok=True)
os.makedirs("paper_draft/v5_15072026_arvix/review", exist_ok=True)

# Generate frequency points
f = np.logspace(np.log10(20), np.log10(2048), 500)

# Qmax constraint
Q_max = 32
# Theoretical maximum duration effectively resolved at Q=32
# T ~ Q / f
t_max = Q_max / f

fig, ax = plt.subplots(figsize=(8, 6))

# Plot the boundary
ax.plot(f, t_max, color='darkred', linewidth=2.5, linestyle='--', label=r'Theoretical Bound ($T_{max} = Q_{max} / f$)')

# Shade the valid detection space
ax.fill_between(f, 0.001, t_max, color='steelblue', alpha=0.2, label='Covered Space (Broadband / Short Transient)')

# Shade the blind spot
ax.fill_between(f, t_max, 100, color='indianred', alpha=0.2, hatch='//', label='Blind Spot (Monochromatic / Long Transient)')

# Scatter some qualitative morphologies
# Blips: ~100-300 Hz, ~0.01-0.05s
ax.scatter([150, 200, 250], [0.02, 0.015, 0.03], color='blue', marker='o', s=100, label='Blips', edgecolor='black')
# Tomtes: ~50-100 Hz, ~0.05-0.1s
ax.scatter([70, 90], [0.08, 0.06], color='cyan', marker='s', s=100, label='Tomtes', edgecolor='black')
# Scattering: ~20-60 Hz, ~0.5-2s
ax.scatter([30, 40, 50], [1.5, 0.8, 2.0], color='green', marker='^', s=100, label='Scattered Light', edgecolor='black')

# A hypothetical long-duration monochromatic signal
# e.g., continuous wave or very long inspiral
ax.scatter([500, 800], [5.0, 2.0], color='darkred', marker='X', s=150, label='Unmodeled Long Transients', edgecolor='black')

ax.set_xscale('log')
ax.set_yscale('log')
ax.set_xlim(20, 2048)
ax.set_ylim(0.005, 10)

ax.set_xlabel('Central Frequency (Hz)', fontsize=12, fontweight='bold')
ax.set_ylabel('Signal Duration (s)', fontsize=12, fontweight='bold')
ax.set_title('Pipeline Parameter Space Coverage ($Q_{max} = 32$)', fontsize=14, fontweight='bold')

ax.legend(loc='upper right', framealpha=0.9, fontsize=10)
ax.grid(True, which="both", ls="--", alpha=0.5)

plt.tight_layout()
out_path = "paper_draft/v5_15072026_arvix/review/parameter_space_blindspot.png"
plt.savefig(out_path, dpi=300)
print(f"Saved plot to {out_path}")
