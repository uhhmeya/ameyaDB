import io
import csv
import contextlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy.stats import binom
from qiskit.circuit import Gate
import swap_qs
from swap_experiments import EXPERIMENTS, IMPLEMENTATIONS, SEED, THETA

REPETITIONS = 200
SHOTS = 1000
COLORS = {"cirq": "#2a78d6", "qiskit": "#eb6834"}
MARKERS = {"cirq": "o", "qiskit": "s"}
OFFSETS = {"cirq": -0.15, "qiskit": 0.15}
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BAND = "#e4e3dd"
HALF_WIDTH = 0.38

STATES = {
    "E1": r"$|11\rangle$ vs $|00\rangle$",
    "E2": r"$|{+}{+}\rangle$ vs $|{+}{+}\rangle$",
    "E3": r"$R_y(\theta)^{\otimes 2}|00\rangle$ vs $|00\rangle$",
}
CIRCUIT_STYLE = {"name": "bw", "creglinecolor": "#000000", "displaytext": {"h": "$H$"},
                 "displaycolor": {"measure": ["#FFFFFF", "#000000"]}}
CIRCUIT_SCALE = 0.56
TABLE_WIDTHS = [0.09, 0.13, 0.08, 0.26, 0.13, 0.19, 0.12]
TABLE_HEADER = ["Exp.", "$U$", "$V$", r"$|\phi_1\rangle$", r"$|\phi_2\rangle$",
                r"$|\langle\phi_1|\phi_2\rangle|^2$", "$P(0)$"]
TABLE_ROWS = [
    ["E1", "$X$", "$I$", r"$|11\rangle$", r"$|00\rangle$", "$0$", "$1/2$"],
    ["E2", "$H$", "$H$", r"$|{+}{+}\rangle$", r"$|{+}{+}\rangle$", "$1$", "$1$"],
    ["E3", r"$R_y(\theta)$", "$I$", r"$R_y(\theta)^{\otimes 2}|00\rangle$", r"$|00\rangle$", "$1/2$", "$3/4$"],
]

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.fontsize": 8.5,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "xtick.color": INK_SECONDARY,
    "ytick.color": INK_SECONDARY,
    "xtick.major.size": 0,
    "ytick.major.size": 3,
    "axes.labelcolor": INK,
    "text.color": INK,
    "pdf.fonttype": 42,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.03,
})


def estimator_distribution(overlap_sq, shots):
    k = np.arange(shots + 1)
    values = np.maximum(2*k/shots - 1, 0)
    pmf = binom.pmf(k, shots, (1 + overlap_sq)/2)
    mean = float(np.sum(values*pmf))
    sd = float(np.sqrt(max(np.sum(values**2*pmf) - mean**2, 0.0)))
    cdf = np.cumsum(pmf)
    lo = float(values[min(np.searchsorted(cdf, 0.025), shots)])
    hi = float(values[min(np.searchsorted(cdf, 0.975), shots)])
    return mean, sd, lo, hi


def collect():
    rows = []
    for key, title, module in IMPLEMENTATIONS:
        np.random.seed(SEED)
        for exp in EXPERIMENTS:
            transforms_1, transforms_2 = exp[key]
            with contextlib.redirect_stdout(io.StringIO()):
                st = module.SwapTest(prepare_input_states=True, input_state_dim=4, measure=True, copies=SHOTS)
                st.build_circuit(input_1_transforms=transforms_1, input_2_transforms=transforms_2)
            for repetition in range(1, REPETITIONS + 1):
                prob_0, overlap_sq = st.simulate()
                rows.append({"implementation": title, "experiment": exp["label"], "repetition": repetition,
                             "shots": SHOTS, "prob_0": prob_0, "overlap_sq_estimate": overlap_sq,
                             "overlap_sq_theory": exp["overlap_sq"]})
    return rows


def estimates(rows, title, label, column="overlap_sq_estimate"):
    return np.array([r[column] for r in rows if r["implementation"] == title and r["experiment"] == label],
                    dtype=float)


def summarize(rows):
    table = []
    for key, title, module in IMPLEMENTATIONS:
        for exp in EXPERIMENTS:
            est = estimates(rows, title, exp["label"])
            p0 = estimates(rows, title, exp["label"], "prob_0")
            mean_exact, sd_exact, lo, hi = estimator_distribution(exp["overlap_sq"], SHOTS)
            table.append({"implementation": title, "experiment": exp["label"],
                          "theory": exp["overlap_sq"], "p0_theory": (1 + exp["overlap_sq"])/2,
                          "p0_mean": p0.mean(), "est_mean": est.mean(), "est_sd": est.std(ddof=1),
                          "exact_mean": mean_exact, "exact_sd": sd_exact,
                          "coverage": np.mean((est >= lo - 1e-12) & (est <= hi + 1e-12))})
    return table


def print_table(table):
    header = (f"{'impl':<7}{'exp':<5}{'|<.|.>|^2':>10}{'P0 th.':>8}{'mean P0':>9}{'mean est':>10}"
              f"{'SD est':>9}{'exact E':>9}{'exact SD':>10}{'in 95%':>8}")
    print()
    print(f"Repetitions per cell: {REPETITIONS}, shots per repetition: {SHOTS}, numpy seed {SEED}")
    print(header)
    print("-"*len(header))
    for t in table:
        print(f"{t['implementation']:<7}{t['experiment']:<5}{t['theory']:>10.2f}{t['p0_theory']:>8.3f}"
              f"{t['p0_mean']:>9.4f}{t['est_mean']:>10.4f}{t['est_sd']:>9.4f}{t['exact_mean']:>9.4f}"
              f"{t['exact_sd']:>10.4f}{100*t['coverage']:>7.1f}%")


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def style_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6, linestyle="-")
    ax.set_axisbelow(True)
    ax.set_xticks(range(len(EXPERIMENTS)))
    ax.set_xticklabels([f"{e['label']}\n{STATES[e['label']]}" for e in EXPERIMENTS])
    ax.set_xlim(-0.55, len(EXPERIMENTS) - 0.45)


def plot_results(rows, stem):
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.15), layout="constrained")
    jitter = np.random.default_rng(SEED)
    for panel, ax in enumerate(axes):
        residual = panel == 1
        for x0, exp in enumerate(EXPERIMENTS):
            theory = exp["overlap_sq"]
            shift = theory if residual else 0.0
            mean_exact, sd_exact, lo, hi = estimator_distribution(theory, SHOTS)
            ax.fill_between([x0 - HALF_WIDTH, x0 + HALF_WIDTH], lo - shift, hi - shift,
                            color=BAND, linewidth=0, zorder=1)
            ax.plot([x0 - HALF_WIDTH, x0 + HALF_WIDTH], [theory - shift]*2, color=INK, linewidth=1.1,
                    solid_capstyle="butt", zorder=3)
            for key, title, module in IMPLEMENTATIONS:
                est = estimates(rows, title, exp["label"]) - shift
                xs = x0 + OFFSETS[key] + jitter.uniform(-0.075, 0.075, est.size)
                ax.scatter(xs, est, s=4, color=COLORS[key], alpha=0.25, linewidths=0, zorder=2)
                ax.errorbar(x0 + OFFSETS[key], est.mean(), yerr=est.std(ddof=1), fmt=MARKERS[key],
                            color=COLORS[key], markersize=6.5, markeredgecolor="white", markeredgewidth=1.0,
                            elinewidth=1.3, capsize=3.0, capthick=1.3, zorder=4)
        style_axes(ax)
    axes[0].set_ylim(-0.05, 1.08)
    axes[0].set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    axes[0].set_ylabel(r"Estimated $|\langle\phi_1|\phi_2\rangle|^2$")
    axes[0].set_title("Squared overlap", loc="left")
    lim = 1.15*max(abs(estimates(rows, t, e["label"]) - e["overlap_sq"]).max()
                   for _, t, _ in IMPLEMENTATIONS for e in EXPERIMENTS)
    axes[1].set_ylim(-lim, lim)
    axes[1].set_ylabel(r"Estimate $-$ theory")
    axes[1].set_title("Deviation from theory", loc="left")
    for letter, ax in zip("ab", axes):
        ax.text(-0.16, 1.035, f"({letter})", transform=ax.transAxes, fontsize=10, fontweight="bold",
                va="bottom")
    handles = [
        Line2D([], [], marker=MARKERS["cirq"], color=COLORS["cirq"], linestyle="none", markersize=6.5,
               markeredgecolor="white", label="Cirq (swap_cirq.py)"),
        Line2D([], [], marker=MARKERS["qiskit"], color=COLORS["qiskit"], linestyle="none", markersize=6.5,
               markeredgecolor="white", label="Qiskit (swap_qs.py)"),
        Line2D([], [], color=INK, linewidth=1.1, label="Theory"),
        Patch(facecolor=BAND, label="95% shot-noise interval"),
    ]
    fig.legend(handles=handles, loc="outside upper center", ncol=4, frameon=False, handletextpad=0.4,
               columnspacing=1.6)
    fig.savefig(f"{stem}.pdf")
    fig.savefig(f"{stem}.png")
    plt.close(fig)


def generic_circuit():
    with contextlib.redirect_stdout(io.StringIO()):
        st = swap_qs.SwapTest(prepare_input_states=True, input_state_dim=4, measure=True)
        st.build_circuit(input_1_transforms=[Gate("U", 1, [], label="$U$")],
                         input_2_transforms=[Gate("V", 1, [], label="$V$")])
    return st.circuit


def draw_table(ax):
    ax.axis("off")
    edges = np.concatenate([[0.0], np.cumsum(TABLE_WIDTHS)])
    centers = (edges[:-1] + edges[1:])/2
    for y, row in zip([0.885, 0.70, 0.55, 0.40], [TABLE_HEADER] + TABLE_ROWS):
        for i, cell in enumerate(row):
            ax.text(0.01 if i == 0 else centers[i], y, cell, transform=ax.transAxes, va="center",
                    ha="left" if i == 0 else "center", fontsize=9)
    for y, width in ((0.97, 1.0), (0.80, 0.6), (0.31, 1.0)):
        ax.plot([0, 1], [y, y], color=INK, linewidth=width, transform=ax.transAxes, clip_on=False)
    notes = [
        r"$|\phi_1\rangle = U^{\otimes 2}|00\rangle$ on $(q_1, q_2)$,   "
        r"$|\phi_2\rangle = V^{\otimes 2}|00\rangle$ on $(q_3, q_4)$",
        r"$P(0) = \frac{1}{2}\,(1 + |\langle\phi_1|\phi_2\rangle|^2)$ for the ancilla $q_0$",
        rf"$\theta = 2\arccos 2^{{-1/4}} \approx {THETA:.4f}$ rad, so "
        r"$|\langle 0|R_y(\theta)|0\rangle|^2 = 2^{-1/2}$",
    ]
    for y, note in zip([0.20, 0.10, 0.0], notes):
        ax.text(0.01, y, note, transform=ax.transAxes, va="center", fontsize=8, color=INK_SECONDARY)


def plot_circuit_figure(stem):
    circuit = generic_circuit()
    probe = circuit.draw("mpl", style=CIRCUIT_STYLE, initial_state=True)
    natural_w, natural_h = probe.get_size_inches()
    plt.close(probe)
    circuit_w, circuit_h = natural_w*CIRCUIT_SCALE, natural_h*CIRCUIT_SCALE
    fig_w, title_h = 7.0, 0.12
    fig_h = circuit_h + title_h
    fig = plt.figure(figsize=(fig_w, fig_h))
    ax_circuit = fig.add_axes([0.0, 0.0, circuit_w/fig_w, circuit_h/fig_h])
    circuit.draw("mpl", style=CIRCUIT_STYLE, initial_state=True, ax=ax_circuit)
    table_left = circuit_w + 0.3
    ax_table = fig.add_axes([table_left/fig_w, 0.1, (fig_w - table_left)/fig_w, 0.72])
    draw_table(ax_table)
    for x, letter, title in ((0.0, "a", "Swap-test circuit"), (table_left/fig_w, "b", "State preparations")):
        fig.text(x, 1.0, f"({letter})", fontsize=10, fontweight="bold", va="top")
        fig.text(x + 0.045, 1.0, title, fontsize=9, va="top")
    fig.savefig(f"{stem}.pdf")
    fig.savefig(f"{stem}.png")
    plt.close(fig)


def main():
    rows = collect()
    write_csv(rows, "swap_results.csv")
    print_table(summarize(rows))
    plot_circuit_figure("fig1_swap_test_circuit")
    plot_results(rows, "fig2_overlap_estimates")
    print()
    print("wrote swap_results.csv, fig1_swap_test_circuit.pdf/.png, fig2_overlap_estimates.pdf/.png")


if __name__ == '__main__':
    main()
