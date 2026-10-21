"""Render cleaned map selections as PNGs. Requires matplotlib.

python plot_activity_map_matplotlib.py
"""
import argparse
import collections
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
import numpy as np

from plot_activity_map import LABELS, COLORS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=Path, default=Path("cleaned/map_cells.csv"))
    parser.add_argument("--map", type=Path, default=Path("survey_cad_full_labelled_3.png"))
    parser.add_argument("--output-dir", type=Path, default=Path("plots"))
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()
    image = plt.imread(args.map)
    height, width = image.shape[:2]
    with args.cells.open(encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f))
    unique = {(r["visit_id"], r["activity"], int(r["column"]), int(r["row"])) for r in records}
    if any(not (1 <= x <= 30 and 1 <= y <= 24) for _, _, x, y in unique):
        raise ValueError("Invalid grid coordinate")
    counts = collections.Counter((a, x, y) for _, a, x, y in unique)
    if not counts:
        raise ValueError("No map selections to plot")
    keys = list(LABELS) + sorted({a for a, _, _ in counts} - LABELS.keys())
    present = [a for a in keys if any(k[0] == a for k in counts)]
    color = {a: COLORS[i % len(COLORS)] for i, a in enumerate(keys)}
    maximum = max(counts.values())
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def background(ax):
        ax.imshow(image, extent=(0, width, height, 0), alpha=.72)
        ax.set(xlim=(0, width), ylim=(height, 0), aspect="equal")
        ax.axis("off")

    fig, ax = plt.subplots(figsize=(17, 13))
    background(ax)
    # Draw large circles first; exact cell centers are preserved (no jitter).
    for (activity, x, y), n in sorted(counts.items(), key=lambda item: -item[1]):
        ax.scatter((x - .5) * width / 30, (y - .5) * height / 24,
                   s=600 * n / maximum, c=color[activity], alpha=.6,
                   edgecolors="white", linewidths=.6)
    for i, activity in enumerate(present):
        (a, x, y), n = min(((k, n) for k, n in counts.items() if k[0] == activity),
                           key=lambda item: (-item[1], item[0][2], item[0][1]))
        # Labels in a side column keep densely overlapping peaks readable.
        ax.annotate(f"{LABELS.get(a, a)} ({n})", xy=((x-.5)*width/30, (y-.5)*height/24),
                    xycoords="data", xytext=(1.02, .96-i*.065), textcoords="axes fraction",
                    color=color[a], fontsize=10, fontweight="bold", va="center",
                    arrowprops=dict(arrowstyle="-", color=color[a], lw=.8),
                    annotation_clip=False)
    ax.set_title("Hunt Library — activity selection clusters", fontsize=19, pad=16)
    handles = [Line2D([], [], marker="o", linestyle="", color=color[a], label=LABELS.get(a, a), markersize=8) for a in present]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, -.015), ncol=3, frameon=False)
    fig.text(.06, .025, "Circle area = visits selecting a cell. Labels identify peak cells (ties: top-left).\n"
             "Selections are discrete grid cells, not exact positions or dwell times. Overlapping colors can obscure one another.", fontsize=10)
    fig.subplots_adjust(left=.02, right=.77, top=.94, bottom=.14)
    overview = args.output_dir / "activity_clusters.png"
    fig.savefig(overview, dpi=args.dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Separate panels reveal selections hidden by overlapping activities.
    fig, axes = plt.subplots((len(present)+2)//3, 3, figsize=(20, 5.6*((len(present)+2)//3)), squeeze=False)
    for ax in axes.flat:
        ax.axis("off")
    norm = Normalize(vmin=0, vmax=maximum)
    for ax, activity in zip(axes.flat, present):
        background(ax)
        grid = np.zeros((24, 30))
        for (a, x, y), n in counts.items():
            if a == activity:
                grid[y-1, x-1] = n
        cmap = LinearSegmentedColormap.from_list(activity, ["white", color[activity]])
        masked = np.ma.masked_equal(grid, 0)
        plot = ax.imshow(masked, extent=(0, width, height, 0), origin="upper", interpolation="nearest",
                         cmap=cmap, norm=norm, alpha=.78)
        nvisits = len({v for v, a, _, _ in unique if a == activity})
        ax.set_title(f"{LABELS.get(activity, activity)} — {nvisits} mapped visits", fontsize=12)
        bar = fig.colorbar(plot, ax=ax, fraction=.035, pad=.015)
        bar.set_label("Visits selecting cell", fontsize=9)
    fig.suptitle("Activity heatmaps — shared count scale across activities", fontsize=20)
    fig.text(.02, .015, "Blank cells: no recorded selections. Colors identify activity; darker cells indicate more visits. No smoothing or dwell-time inference.", fontsize=11)
    fig.tight_layout(rect=(0, .035, 1, .96))
    panels = args.output_dir / "activity_heatmaps.png"
    fig.savefig(panels, dpi=args.dpi, facecolor="white")
    plt.close(fig)
    print(f"Saved {overview} and {panels}; {len(unique)} unique cell selections.")


if __name__ == "__main__":
    main()
