import csv
import glob
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
PICK = "#2a78d6"
REST = "#898781"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#6250d6", "#e34948"]

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK_2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "legend.frameon": False,
    "font.size": 10,
})


def cpu_number(path):
    match = re.search(r"cpu(-?\d+)", Path(path).stem)
    return int(match.group(1)) if match else 0


def cpu_label(path):
    match = re.search(r"cpu(-?\d+)", Path(path).stem)
    return f"CPU {match.group(1)}" if match else Path(path).stem


def load(path):
    with open(path, newline="") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["rank"]))
    cycles = [float(r["cycles"]) for r in rows]
    picked = [r["selected"] == "1" for r in rows]
    return cycles, picked


def limits(values, keep=1.0):
    ordered = sorted(values)
    top = ordered[int((len(ordered) - 1) * keep)]
    pad = max(0.3, 0.05 * (top - ordered[0]))
    return ordered[0] - pad, top + pad


def plot_one(path):
    label = cpu_label(path)
    cycles, picked = load(path)
    n = len(cycles)
    share = n // 16
    zoom = min(n, 2 * share)
    ranks = list(range(1, n + 1))
    pick_x = [r for r, p in zip(ranks, picked) if p]
    pick_y = [c for c, p in zip(cycles, picked) if p]
    rest_x = [r for r, p in zip(ranks[:zoom], picked[:zoom]) if not p]
    rest_y = [c for c, p in zip(cycles[:zoom], picked[:zoom]) if not p]

    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 4.8))

    lo, hi = limits(cycles, keep=0.98)
    left.axvspan(0.5, zoom + 0.5, color=GRID, alpha=0.6, linewidth=0)
    left.plot(ranks, cycles, color=REST, linewidth=2,
              solid_capstyle="round", label=f"All {n} lines")
    left.plot(pick_x, pick_y, color=PICK, linewidth=4,
              solid_capstyle="round", label=f"{len(pick_x)} chosen lines")
    left.text(zoom + 8, hi - 0.03 * (hi - lo),
              f"Shaded: fastest {zoom} lines,\nzoomed in on the right",
              color=INK_2, fontsize=9, va="top")
    left.set_xlim(0, n + 1)
    left.set_ylim(lo, hi)
    left.set_xlabel("Lines sorted from fastest to slowest")
    left.set_ylabel("Average LLC access time (cycles)")
    left.set_title(f"All {n} lines", loc="left", color=INK)
    left.legend(loc="lower right")

    zlo, zhi = limits(cycles[:zoom])
    right.axvline(share + 0.5, color=MUTED, linewidth=1)
    right.text(share - 0.5, zhi - 0.03 * (zhi - zlo),
               f"{n} / 16 = {share} lines,\none slice's share",
               color=INK_2, fontsize=9, va="top", ha="right")
    right.scatter(rest_x, rest_y, s=34, color=REST, edgecolor=SURFACE,
                  linewidth=1.5, zorder=3, label="Other lines")
    right.scatter(pick_x, pick_y, s=34, color=PICK, edgecolor=SURFACE,
                  linewidth=1.5, zorder=4, label=f"{len(pick_x)} chosen lines")
    right.set_xlim(0, zoom + 1)
    right.set_ylim(zlo, zhi)
    right.set_xlabel("Lines sorted from fastest to slowest")
    right.set_ylabel("Average LLC access time (cycles)")
    right.set_title(f"Fastest {zoom} lines", loc="left", color=INK)
    right.legend(loc="lower right")

    fig.suptitle(f"{label}: LLC access time of {n} target lines",
                 x=0.01, ha="left", fontsize=13, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out = Path(path).with_suffix(".png")
    fig.savefig(out, dpi=150)
    plt.close(fig)

    head = cycles[:zoom]
    steps = [b - a for a, b in zip(head, head[1:])]
    jump = max(range(len(steps)), key=lambda i: steps[i])
    print(f"{label}: chosen lines average {sum(pick_y) / len(pick_y):.2f} cycles, "
          f"median of all lines {cycles[n // 2]:.2f} cycles, "
          f"biggest jump in the fastest {zoom} lines is "
          f"{steps[jump]:.2f} cycles after line {jump + 1}  ->  {out}")


def plot_all(paths):
    paths = sorted(paths, key=cpu_number)[: len(SERIES)]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    lows, highs = [], []
    for color, path in zip(SERIES, paths):
        cycles, _ = load(path)
        lo, hi = limits(cycles, keep=0.98)
        lows.append(lo)
        highs.append(hi)
        ax.plot(range(1, len(cycles) + 1), cycles, color=color, linewidth=2,
                solid_capstyle="round", label=cpu_label(path))
    ax.set_ylim(min(lows), max(highs))
    ax.set_xlabel("Lines sorted from fastest to slowest")
    ax.set_ylabel("Average LLC access time (cycles)")
    ax.set_title("Sorted average latency on each CPU", loc="left", color=INK)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig("all_cpus.png", dpi=150)
    plt.close(fig)
    print("Saved all_cpus.png")


def main():
    paths = sys.argv[1:] or sorted(glob.glob("results_cpu*.csv"), key=cpu_number)
    if not paths:
        sys.exit("No results_cpu*.csv files found. Run ./answer first.")
    for path in paths:
        plot_one(path)
    if len(paths) > 1:
        plot_all(paths)


if __name__ == "__main__":
    main()