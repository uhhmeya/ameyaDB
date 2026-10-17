import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import hhl_cirq
import hhl_qiskit
from hhl_common import SYSTEMS, parameters

ROOT = Path(__file__).resolve().parent.parent
RESULTS = json.loads((ROOT / "results" / "results.json").read_text())
FIGURES = ROOT / "paper" / "figures"
TABLES = ROOT / "paper" / "tables"
PREVIEWS = ROOT / "results" / "previews"

ORDER = ["diagonal2", "coupled2", "chain4", "chain3"]
LABEL = {"diagonal2": "E1", "coupled2": "E2", "chain4": "E3", "chain3": "E4"}
NAME = {"diagonal2": "two uncoupled springs", "coupled2": "two coupled blocks",
        "chain4": "chain of four blocks", "chain3": "chain of three blocks"}
SHORT = {"diagonal2": "diagonal", "coupled2": "coupled", "chain4": "four blocks",
         "chain3": "three blocks (padded)"}
MACRO = {"diagonal2": "EOne", "coupled2": "ETwo", "chain4": "EThree", "chain3": "EFour"}

INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
TEXT_WIDTH = 5.95

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 7.5, "pdf.fonttype": 42,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.6, "axes.labelcolor": INK_2,
    "axes.titlesize": 8, "axes.titlecolor": INK, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "axes.axisbelow": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.major.size": 2.5, "ytick.major.size": 0, "legend.frameon": False,
    "legend.fontsize": 7.5, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})


def save(fig, name):
    FIGURES.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}.pdf")
    fig.savefig(PREVIEWS / f"{name}.png", dpi=200)
    plt.close(fig)


def figure_results():
    fig, axes = plt.subplots(1, 4, figsize=(TEXT_WIDTH, 1.95),
                             gridspec_kw={"width_ratios": [2, 2, 4, 4]})
    width = 0.3
    for ax, key in zip(axes, ORDER):
        rec = RESULTS["experiments"][key]
        x = np.abs(rec["x_classical"])
        pos = np.arange(len(x))
        for shift, name, colour in ((-width / 2, "cirq", BLUE), (width / 2, "qiskit", ORANGE)):
            s = rec["sampled"][name]
            ax.bar(pos + shift, s["x_abs"], width=width - 0.04, color=colour,
                   label={"cirq": "Cirq", "qiskit": "Qiskit"}[name], zorder=2)
            ax.errorbar(pos + shift, s["x_abs"], yerr=s["x_abs_err"], fmt="none",
                        ecolor=INK, elinewidth=0.7, capsize=1.5, capthick=0.7, zorder=3)
        ax.hlines(x, pos - 0.38, pos + 0.38, color=INK, linewidth=1.1, zorder=4,
                  label="classical solution")
        names = [f"$x_{i + 1}$" for i in range(rec["n_unknowns"])]
        names += ["pad"] * (len(x) - rec["n_unknowns"])
        ax.set_xticks(pos, names)
        ax.set_xlim(-0.65, len(x) - 0.35)
        ax.set_ylim(0, 1.18 * x.max())
        ax.set_title(f"{LABEL[key]}  {SHORT[key]}", fontsize=7, loc="left")
    axes[0].set_ylabel("displacement $|x_i|$")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.09),
               handlelength=1.4, columnspacing=1.6)
    fig.tight_layout(w_pad=0.8)
    save(fig, "fig_results")


def figure_clock():
    fig, axes = plt.subplots(1, 2, figsize=(TEXT_WIDTH, 2.0),
                             gridspec_kw={"width_ratios": [1, 2.6]})
    for ax, key in zip(axes, ("diagonal2", "coupled2")):
        rec = RESULTS["experiments"][key]
        p = rec["params"]
        N = 2 ** p["n_clock"]
        dist = np.array(rec["clock_distribution"])
        k = np.arange(N)
        per_k = p["lam_hi"] / (N - 1)
        ax.bar(k, dist, width=0.62 if N <= 8 else 0.72, color=BLUE, zorder=2)
        ax.set_ylim(0, 1.40 * dist.max())
        for j, lam in enumerate(rec["eigenvalues_for_plots"]):
            pos = lam / per_k
            ax.vlines(pos, 0, 1.12 * dist.max(), color=INK, linewidth=0.7, zorder=3)
            ax.text(pos, 1.15 * dist.max(), f"$\\lambda_{j + 1}={lam:.3f}$".replace(".000", ""),
                    ha="center", va="bottom", color=INK, fontsize=7)
        if N <= 8:
            ax.set_xticks(k)
            ax.set_xlim(-0.6, N - 0.4)
        else:
            cut = p["C"] / per_k
            ax.axvspan(-0.5, cut, color="#f0efec", zorder=1)
            ax.text(cut / 2 - 0.25, 0.55 * dist.max(), "$\\lambda_k < C$:\nancilla\nnot rotated",
                    ha="center", va="center", color=INK_2, fontsize=6.5)
            ax.set_xlim(-0.5, N - 0.5)
            ax.set_xticks(np.arange(0, N, 8))
            top = ax.secondary_xaxis("top", functions=(lambda v: v * per_k, lambda v: v / per_k))
            top.set_xlabel("eigenvalue it stands for, $\\lambda_k$", color=INK_2)
            top.spines["top"].set_visible(True)
            top.spines["top"].set_color(AXIS)
            top.tick_params(colors=MUTED, labelcolor=INK_2, length=2.5, width=0.6)
        ax.set_xlabel(f"clock value $k$\n({'ab'[key == 'coupled2']}) {LABEL[key]}: "
                      f"{p['n_clock']} clock qubits", linespacing=1.6)
    axes[0].set_ylabel("probability")
    fig.tight_layout(w_pad=1.2)
    save(fig, "fig_clock")


def figure_sweep():
    fig, axes = plt.subplots(1, 2, figsize=(TEXT_WIDTH, 2.3))
    series = (("coupled2", BLUE, "o"), ("chain4", ORANGE, "s"), ("chain3", AQUA, "^"))
    for key, colour, marker in series:
        rows = RESULTS["sweep"][key]
        n = [r["n_clock"] for r in rows]
        style = dict(color=colour, marker=marker, markersize=4.5, linewidth=1.4,
                     markeredgecolor="white", markeredgewidth=0.7, zorder=3)
        axes[0].plot(n, [r["rel_err"] for r in rows], label=f"{LABEL[key]} ({NAME[key]})", **style)
        axes[1].plot(n, [r["cx"] for r in rows], **style)
    n = np.array([r["n_clock"] for r in RESULTS["sweep"]["coupled2"]])
    guide = 0.15 * 2.0 ** (-(n - 2))
    axes[0].plot(n, guide, color=MUTED, linewidth=0.8, zorder=2)
    axes[0].annotate("error halves\nper extra qubit", (n[-1], guide[-1]), xytext=(5, 0),
                     textcoords="offset points", va="center", color=INK_2, fontsize=6.5)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("relative error of $|x|$")
    axes[0].set_title("Accuracy", loc="left")
    axes[1].set_yscale("log")
    axes[1].set_yticks([20, 50, 100, 200, 500, 1000], ["20", "50", "100", "200", "500", "1000"])
    axes[1].set_ylabel("CNOT gates after compilation")
    axes[1].set_title("Cost", loc="left")
    for ax in axes:
        ax.set_xlabel("clock qubits $n$")
        ax.set_xticks(n)
        ax.tick_params(axis="y", which="both", length=0)
        ax.minorticks_off()
    axes[0].set_xlim(n[0] - 0.3, n[-1] + 1.9)
    axes[1].set_xlim(n[0] - 0.3, n[-1] + 0.3)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.08),
               handlelength=2.0, columnspacing=1.6)
    fig.tight_layout(w_pad=1.5)
    save(fig, "fig_sweep")


def figure_circuits():
    system = SYSTEMS["diagonal2"]
    p = parameters(system)
    text = str(hhl_cirq.HHL(system.A, b=system.b, qpe_register_size=p["n_clock"],
                            C=p["C"], t=p["t"]).build_hhl_circuit())
    (PREVIEWS / "circuit_cirq.txt").write_text(text + "\n")
    lines = text.splitlines()
    size = TEXT_WIDTH * 72 / (0.602 * max(len(line) for line in lines))
    fig = plt.figure(figsize=(TEXT_WIDTH, size * 1.22 * len(lines) / 72 + 0.05))
    fig.text(0.0, 0.5, text, family="DejaVu Sans Mono", fontsize=size, color=INK,
             va="center", ha="left", linespacing=1.0)
    save(fig, "fig_circuit_cirq")

    solver = hhl_qiskit.HHL(system.A, system.b, n_clock=p["n_clock"], C=p["C"], t=p["t"])
    top = solver.build_circuit()
    for instruction in top.data[1:]:
        instruction.operation.label = f"   {instruction.operation.label}   "
    save(top.draw("mpl", style="bw", fold=-1, scale=0.6), "fig_circuit_qiskit")
    save(solver._phase_estimation().draw("mpl", style="bw", fold=-1, scale=0.6),
         "fig_circuit_qiskit_qpe")


def num(v, d=3):
    return f"${v:.{d}f}$"


def ens(v, d=3):
    return f"\\ensuremath{{{v:.{d}f}}}"


def pm(v, e, d=3):
    return f"${v:.{d}f} \\pm {e:.{d}f}$"


def sci(v):
    mantissa, exponent = f"{v:.1e}".split("e")
    return f"\\ensuremath{{{mantissa}\\times 10^{{{int(exponent)}}}}}"


def vector(v):
    return "$(" + ",".join(f"{a:g}" for a in v) + ")$"


def pauli_error(value, accepted):
    return np.sqrt(max(1 - value ** 2, 0.0) / accepted)


def write_table(name, column_spec, header, rows):
    lines = [f"\\begin{{tabular}}{{{column_spec}}}", "\\toprule", header + " \\\\", "\\midrule"]
    for row in rows:
        lines.append(row if row == "\\midrule" else row + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / f"{name}.tex").write_text("\n".join(lines) + "\n")


def table_parameters():
    rows = []
    for key in ORDER:
        rec = RESULTS["experiments"][key]
        p = rec["params"]
        n = rec["n_unknowns"]
        size = f"${n}\\times{n}$" + ("" if n == len(rec["b"]) else " (padded)")
        rows.append(" & ".join([
            LABEL[key], NAME[key].capitalize(), size, vector(rec["b"][:n]),
            f"$[{p['lam_lo']:g},\\,{p['lam_hi']:g}]$", p["bounds"],
            str(p["n_clock"]), num(p["t"], 4), str(p["qubits"])]))
    write_table("tab_parameters", "llccclccc",
                " & System & Size & $b$ & $[C,\\Lambda]$ & Bounds from & $n$ & $t$ & Qubits", rows)


def table_textbook():
    tb = RESULTS["textbook"]
    shots = tb["shots"]

    def exact(rec):
        return " & ".join(num(rec[a], 4) for a in "XYZ")

    rows = [
        "Expected values quoted in the listing & " + exact(tb["expected"]),
        "Classical solution (NumPy) & " + exact(tb["classical"]),
        "\\midrule",
        f"Output printed in the book ({shots} repetitions) & " + exact(tb["printed"]),
    ]
    if tb["listing_replay"]:
        rp = tb["listing_replay"]
        rows.append(f"Original listing, unmodified (mean of {rp['runs']} runs) & "
                    + " & ".join(pm(rp["mean"][a], rp["sem"][a], 4) for a in "XYZ"))
    rows += [
        "Our port with $t$ not passed ($t=1$), exact & " + exact(tb["as_printed_exact"]),
        "\\midrule",
        "Our port with $t$ passed, exact & " + exact(tb["fixed_exact"]),
    ]
    for name, label in (("cirq", "Cirq"), ("qiskit", "Qiskit")):
        s = tb["fixed_sampled"][name]
        rows.append(f"{label} with $t$ passed, {shots} repetitions & " + " & ".join(
            pm(s[a], pauli_error(s[a], s["accepted"][a])) for a in "XYZ"))
    write_table("tab_textbook", "lccc",
                "Source & $\\langle X\\rangle$ & $\\langle Y\\rangle$ & $\\langle Z\\rangle$", rows)


def result_rows(key, with_pauli):
    rec = RESULTS["experiments"][key]
    ex, sam = rec["exact"]["cirq"], rec["sampled"]
    shots = RESULTS["meta"]["shots"]
    scale = rec["b_norm"] / rec["params"]["C"]
    rows = []
    for i in range(len(rec["b"])):
        if i < rec["n_unknowns"]:
            rows.append(" & ".join(
                [f"$x_{i + 1}$", num(abs(rec["x_classical"][i])), num(ex["x_abs"][i])]
                + [pm(sam[f]["x_abs"][i], sam[f]["x_abs_err"][i]) for f in ("cirq", "qiskit")]))
        else:
            rows.append(" & ".join(
                ["padding state", "$0$", num(ex["x_abs"][i])]
                + [f"{sam[f]['counts'][1][i]} counts" for f in ("cirq", "qiskit")]))
    norm_err = {f: scale * sam[f]["p_success_err"] / (2 * np.sqrt(sam[f]["p_success"]))
                for f in ("cirq", "qiskit")}
    rows.append(" & ".join(
        ["$\\lVert x\\rVert$", num(rec["x_norm_classical"]), num(ex["x_norm"])]
        + [pm(sam[f]["x_norm"], norm_err[f]) for f in ("cirq", "qiskit")]))
    rows.append(" & ".join(
        ["success probability", num(rec["p_success_ideal"]), num(ex["p_success"])]
        + [pm(sam[f]["p_success"], sam[f]["p_success_err"]) for f in ("cirq", "qiskit")]))
    if with_pauli:
        pl = rec["pauli"]
        for axis in "XYZ":
            cells = [f"$\\langle {axis}\\rangle$", num(pl["classical"][axis]),
                     num(pl["exact"]["cirq"][axis])]
            for f in ("cirq", "qiskit"):
                s = pl["sampled"][f]
                cells.append(pm(s[axis], pauli_error(s[axis], s["accepted"][axis])))
            rows.append(" & ".join(cells))
    return rows


def table_results(name, keys, with_pauli):
    shots = RESULTS["meta"]["shots"]
    rows = []
    for j, key in enumerate(keys):
        if j:
            rows.append("\\midrule")
        rows.append(f"\\multicolumn{{5}}{{l}}{{\\textit{{{LABEL[key]}: {NAME[key]}}}}}")
        rows += result_rows(key, with_pauli)
    write_table(name, "lcccc",
                f" & Classical & Circuit, exact & Cirq, {shots} shots & Qiskit, {shots} shots",
                rows)


def table_summary():
    recs = [RESULTS["experiments"][key] for key in ORDER]
    sweeps = RESULTS["sweep"]

    def rel_err(rec):
        x = np.abs(rec["x_classical"])
        return np.linalg.norm(np.array(rec["exact"]["cirq"]["x_abs"]) - x) / np.linalg.norm(x)

    rows = [
        "Qubits & " + " & ".join(str(r["params"]["qubits"]) for r in recs),
        "Success probability & " + " & ".join(num(r["exact"]["cirq"]["p_success"]) for r in recs),
        "Fidelity with the classical solution & "
        + " & ".join(num(r["exact"]["cirq"]["fidelity"], 4) for r in recs),
        "Relative error of $|x|$ & "
        + " & ".join(f"{100 * rel_err(r):.2f}\\,\\%" for r in recs),
        "CNOT gates after compilation & " + " & ".join(str(r["resources"]["cx"]) for r in recs),
        "Circuit depth after compilation & "
        + " & ".join(str(r["resources"]["depth"]) for r in recs),
    ]
    write_table("tab_summary", "lcccc", " & " + " & ".join(LABEL[k] for k in ORDER), rows)


def macros():
    meta, tb = RESULTS["meta"], RESULTS["textbook"]
    m = {"Shots": str(meta["shots"]), "Seed": str(meta["seed"]),
         "VerPython": meta["python"], "VerCirq": meta["cirq"], "VerQiskit": meta["qiskit"],
         "VerAer": meta["qiskit_aer"], "VerNumpy": meta["numpy"], "VerScipy": meta["scipy"]}

    m["TbShots"] = str(tb["shots"])
    for axis in "XYZ":
        m[f"TbExpected{axis}"] = ens(tb["expected"][axis], 4)
        m[f"TbPrinted{axis}"] = ens(tb["printed"][axis], 4)
        m[f"TbAsPrinted{axis}"] = ens(tb["as_printed_exact"][axis], 4)
        m[f"TbFixed{axis}"] = ens(tb["fixed_exact"][axis], 4)
    m["TbSigmaAsPrinted"] = f"{tb['sigma_vs_as_printed']:.1f}"
    m["TbSigmaExpected"] = f"{tb['sigma_vs_expected']:.1f}"
    m["TbClockAsPrintedLow"] = f"{tb['as_printed_exact']['clock_values'][0]:.2f}"
    m["TbClockAsPrintedHigh"] = f"{tb['as_printed_exact']['clock_values'][1]:.2f}"
    m["TbClockFixedLow"] = f"{tb['fixed_exact']['clock_values'][0]:.2f}"
    m["TbClockFixedHigh"] = f"{tb['fixed_exact']['clock_values'][1]:.2f}"
    m["TbSuccessAsPrinted"] = f"{tb['as_printed_exact']['p_success']:.3f}"
    for axis in "XYZ":
        m[f"TbAccepted{axis}"] = str(tb["printed_accepted"][axis])
    if tb["listing_replay"]:
        rp = tb["listing_replay"]
        m["TbReplayRuns"] = str(rp["runs"])
        worst = max(abs(rp["mean"][a] - tb["expected"][a]) / rp["sem"][a] for a in "XYZ")
        agree = max(abs(rp["mean"][a] - tb["as_printed_exact"][a]) / rp["sem"][a] for a in "XYZ")
        m["TbReplaySigmaExpected"] = f"{worst:.0f}"
        m["TbReplaySigmaAsPrinted"] = f"{agree:.1f}"
        for axis in "XYZ":
            m[f"TbReplay{axis}"] = ens(rp["mean"][axis], 3)

    worst_sampled, worst_framework = 0.0, 0.0
    for key in ORDER:
        rec, name = RESULTS["experiments"][key], MACRO[key]
        p, ex = rec["params"], rec["exact"]["cirq"]
        x = np.abs(rec["x_classical"])
        m[name + "NClock"] = str(p["n_clock"])
        m[name + "Levels"] = str(2 ** p["n_clock"])
        m[name + "Qubits"] = str(p["qubits"])
        m[name + "T"] = f"{p['t']:.4f}"
        m[name + "Resolution"] = f"{p['lam_hi'] / (2 ** p['n_clock'] - 1):.3f}"
        m[name + "SuccessIdeal"] = f"{rec['p_success_ideal']:.3f}"
        m[name + "SuccessExact"] = f"{ex['p_success']:.3f}"
        m[name + "Fidelity"] = f"{ex['fidelity']:.4f}"
        m[name + "Infidelity"] = sci(max(1 - ex["fidelity"], 1e-16))
        rel = np.linalg.norm(np.array(ex["x_abs"]) - x) / np.linalg.norm(x)
        m[name + "RelErrExact"] = f"{100 * rel:.1f}"
        m[name + "Cx"] = str(rec["resources"]["cx"])
        m[name + "Depth"] = str(rec["resources"]["depth"])
        for f, tag in (("cirq", "Cirq"), ("qiskit", "Qiskit")):
            s = rec["sampled"][f]
            m[name + "Accepted" + tag] = str(s["accepted"])
            m[name + "Success" + tag] = f"{s['p_success']:.3f}"
            worst_sampled = max(worst_sampled,
                                np.linalg.norm(np.array(s["x_abs"]) - x) / np.linalg.norm(x))
        worst_framework = max(worst_framework, rec["framework_difference"],
                              rec["clock_max_difference"])
        eig = rec["eigenvalues_for_plots"]
        per_k = p["lam_hi"] / (2 ** p["n_clock"] - 1)
        m[name + "EigLow"] = f"{min(eig):.3f}"
        m[name + "EigHigh"] = f"{max(eig):.3f}"
        m[name + "ClockLow"] = f"{min(eig) / per_k:.2f}"
        m[name + "ClockHigh"] = f"{max(eig) / per_k:.2f}"
        m[name + "ErrorBar"] = f"{rec['b_norm'] / (2 * p['C'] * np.sqrt(meta['shots'])):.4f}"
    for key, rows in RESULTS["sweep"].items():
        for row in rows:
            worst_framework = max(worst_framework, row["framework_difference"])
    m["WorstSampledError"] = f"{100 * worst_sampled:.1f}"

    z = []
    for key in ORDER:
        rec = RESULTS["experiments"][key]
        for f in ("cirq", "qiskit"):
            s = rec["sampled"][f]
            z += [abs(a - b) / e for a, b, e in
                  zip(s["x_abs"], rec["exact"][f]["x_abs"], s["x_abs_err"]) if e > 0]
    m["WorstSigma"] = f"{max(z):.1f}"
    m["NumSampledComponents"] = str(len(z))
    m["FrameworkDifference"] = sci(worst_framework)

    for key in ("coupled2", "chain4", "chain3"):
        rows = RESULTS["sweep"][key]
        n = np.array([r["n_clock"] for r in rows])
        slope = np.polyfit(n, np.log2([r["rel_err"] for r in rows]), 1)[0]
        m[MACRO[key] + "ErrorFactor"] = f"{2 ** slope:.2f}"
        big = [r for r in rows if r["n_clock"] >= 6]
        growth = (big[-1]["cx"] / big[0]["cx"]) ** (1 / (len(big) - 1))
        m[MACRO[key] + "CxGrowth"] = f"{growth:.2f}"
        for r in rows:
            if r["n_clock"] in (4, 8, 9):
                tag = {4: "Four", 8: "Eight", 9: "Nine"}[r["n_clock"]]
                m[MACRO[key] + "RelErr" + tag] = f"{100 * r['rel_err']:.2f}"
                m[MACRO[key] + "Cx" + tag] = str(r["cx"])
    m["SweepMaxClock"] = str(max(r["n_clock"] for r in RESULTS["sweep"]["coupled2"]))

    for f, tag in (("cirq", "Cirq"), ("qiskit", "Qiskit")):
        counts = RESULTS["experiments"]["diagonal2"]["sampled"][f]["counts"]
        for a, a_name in enumerate(("Zero", "One")):
            for i, i_name in enumerate(("Zero", "One")):
                m[f"EOne{tag}Count{a_name}{i_name}"] = str(counts[a][i])
    e1 = RESULTS["experiments"]["diagonal2"]["sampled"]["cirq"]
    m["EOneCirqXOne"] = f"{e1['x_abs'][0]:.3f}"
    m["EOneCirqXTwo"] = f"{e1['x_abs'][1]:.3f}"

    b2 = RESULTS["experiments"]["coupled2"]["b"]
    m["ETwoAngle"] = f"{2 * np.arctan2(b2[1], b2[0]):.4f}"
    clock = np.array(RESULTS["experiments"]["coupled2"]["clock_distribution"])
    m["ETwoPeakClock"] = str(int(np.argmax(clock)))
    m["ETwoPeakProbability"] = f"{clock.max():.2f}"

    import subprocess
    import sys
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                               capture_output=True, text=True,
                               cwd=Path(__file__).resolve().parent).stdout
    m["NumTests"] = collected.strip().splitlines()[-1].split()[0]

    lines = ["% Generated by code/make_paper_assets.py -- do not edit by hand."]
    lines += [f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in m.items()]
    (ROOT / "paper" / "results_macros.tex").write_text("\n".join(lines) + "\n")


def excerpt(module, names):
    import ast
    import textwrap
    source = (ROOT / "code" / module).read_text()
    lines = source.splitlines()
    found = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    found[f"{node.name}.{item.name}"] = item
        elif isinstance(node, ast.FunctionDef):
            found.setdefault(node.name, node)
    parts = [textwrap.dedent("\n".join(lines[found[n].lineno - 1: found[n].end_lineno]))
             for n in names]
    return "\n\n".join(parts) + "\n"


def copy_code():
    target = ROOT / "paper" / "code"
    target.mkdir(exist_ok=True)
    for name in ("hhl_common.py", "hhl_cirq.py", "hhl_qiskit.py"):
        (target / name).write_text((ROOT / "code" / name).read_text())
    (target / "excerpt_parameters.py").write_text(excerpt(
        "hhl_common.py", ["gershgorin_bounds", "evolution_time", "clock_eigenvalues",
                          "rotation_angles"]))
    (target / "excerpt_cirq_inversion.py").write_text(excerpt(
        "hhl_cirq.py", ["EigenValueInversion._decompose_"]))
    (target / "excerpt_qiskit_circuit.py").write_text(excerpt(
        "hhl_qiskit.py", ["HHL._phase_estimation", "HHL.build_circuit"]))


if __name__ == "__main__":
    figure_results()
    figure_clock()
    figure_sweep()
    figure_circuits()
    table_parameters()
    table_textbook()
    table_results("tab_results_small", ["diagonal2", "coupled2"], with_pauli=True)
    table_results("tab_results_large", ["chain4", "chain3"], with_pauli=False)
    table_summary()
    macros()
    copy_code()
    print("figures, tables and macros written to", ROOT / "paper")
