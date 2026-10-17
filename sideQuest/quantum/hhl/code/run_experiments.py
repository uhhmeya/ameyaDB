import json
import platform
from fractions import Fraction
from pathlib import Path

import cirq
import numpy as np
import qiskit
import qiskit_aer
import scipy

import hhl_cirq
import hhl_qiskit
import textbook_replay
from hhl_common import SYSTEMS, decode, fidelity, parameters, pauli_expectations

SHOTS = 8192
SEED = 2026
SWEEP_CLOCKS = list(range(2, 10))
RESULTS_FILE = Path(__file__).resolve().parent.parent / "results" / "results.json"


def make_solvers(system, p):
    return {
        "cirq": hhl_cirq.HHL(system.A, b=system.b, qpe_register_size=p["n_clock"],
                             C=p["C"], t=p["t"]),
        "qiskit": hhl_qiskit.HHL(system.A, system.b, n_clock=p["n_clock"],
                                 C=p["C"], t=p["t"]),
    }


def _plain(obj):
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _plain(obj.tolist())
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, complex):
        return [obj.real, obj.imag]
    return obj


def run_experiment(key, shots=SHOTS, seed=SEED):
    system = SYSTEMS[key]
    p = parameters(system)
    b_norm = np.linalg.norm(system.b)
    x = np.linalg.solve(system.A, system.b)
    one_qubit = len(system.b) == 2

    record = {
        "key": key, "title": system.title, "n_unknowns": system.n_unknowns,
        "A": system.A, "b": system.b, "b_norm": b_norm,
        "x_classical": x, "x_norm_classical": np.linalg.norm(x),
        "params": dict(p, qubits=1 + p["n_clock"] + int(np.log2(len(system.b))),
                       bounds="by inspection" if system.bounds else "Gershgorin"),
        "eigenvalues_for_plots": np.linalg.eigvalsh(system.A),
        "p_success_ideal": (p["C"] * np.linalg.norm(x) / b_norm) ** 2,
        "exact": {}, "sampled": {},
        "pauli": {"classical": pauli_expectations(np.outer(x, x.conj())),
                  "exact": {}, "sampled": {}} if one_qubit else None,
    }
    solvers = make_solvers(system, p)
    joints = {}
    for name, solver in solvers.items():
        exact = solver.exact()
        joints[name] = exact["joint"]
        record["exact"][name] = dict(decode(exact["joint"], p["C"], b_norm),
                                     fidelity=fidelity(exact["rho1"], x))
        counts = solver.sample(shots, seed)
        record["sampled"][name] = dict(decode(counts, p["C"], b_norm, shots=shots),
                                       counts=counts)
        if one_qubit:
            record["pauli"]["exact"][name] = pauli_expectations(exact["rho1"])
            record["pauli"]["sampled"][name] = solver.sample_pauli(shots, seed + 1)
    record["framework_difference"] = float(np.max(np.abs(joints["cirq"] - joints["qiskit"])))
    record["clock_distribution"] = solvers["qiskit"].clock_distribution()
    record["clock_max_difference"] = float(np.max(np.abs(
        solvers["cirq"].clock_distribution() - record["clock_distribution"])))
    record["resources"] = solvers["qiskit"].resources()
    return record


def textbook_check(shots=5000, seed=SEED, replay_runs=100):
    A = np.array([[4.30213466 - 6.01593490e-08j, 0.23531802 + 9.34386156e-01j],
                  [0.23531882 - 9.34388383e-01j, 0.58386534 + 6.01593489e-08j]])
    t = 0.358166 * np.pi
    n_clock = 4
    prep = [cirq.rx(1.276359), cirq.rz(1.276359)]
    b = cirq.unitary(prep[1]) @ cirq.unitary(prep[0]) @ np.array([1, 0])
    expected = {"X": 0.144130, "Y": 0.413217, "Z": -0.899154}
    printed = {"X": 0.21283255086071984, "Y": 0.3746130030959752,
               "Z": -0.8580246913580247}
    eigenvalues = np.linalg.eigvalsh(A)

    def exact_record(solver, time):
        exact = solver.exact()
        rec = pauli_expectations(exact["rho1"])
        rec["p_success"] = float(np.trace(exact["rho1"]).real)
        rec["clock_values"] = eigenvalues * time * 2 ** n_clock / (2 * np.pi)
        return rec

    printed_accepted = {}
    for axis, value in printed.items():
        reduced = Fraction((1 - value) / 2).limit_denominator(5000).denominator
        printed_accepted[axis] = reduced * round(0.26 * 5000 / reduced)

    def worst_sigma(model):
        return max(abs(printed[axis] - model[axis])
                   / np.sqrt((1 - model[axis] ** 2) / printed_accepted[axis]) for axis in "XYZ")

    as_printed = exact_record(
        hhl_cirq.HHL(A, initial_state_transforms=prep, qpe_register_size=n_clock), 1.0)
    fixed_cirq = hhl_cirq.HHL(A, initial_state_transforms=prep,
                              qpe_register_size=n_clock, t=t)
    fixed_qiskit = hhl_qiskit.HHL(A, b, n_clock=n_clock, t=t)
    fixed = exact_record(fixed_cirq, t)
    x = np.linalg.solve(A, b)
    return {
        "expected": expected, "printed": printed, "shots": shots,
        "printed_accepted": printed_accepted,
        "classical": pauli_expectations(np.outer(x, x.conj())),
        "as_printed_exact": as_printed,
        "fixed_exact": fixed,
        "fixed_exact_qiskit": pauli_expectations(fixed_qiskit.exact()["rho1"]),
        "fixed_sampled": {"cirq": fixed_cirq.sample_pauli(shots, seed),
                          "qiskit": fixed_qiskit.sample_pauli(shots, seed)},
        "sigma_vs_as_printed": worst_sigma(as_printed),
        "sigma_vs_expected": worst_sigma(fixed),
        "listing_replay": (textbook_replay.replay(replay_runs, seed)
                           if textbook_replay.LISTING.exists() else None),
    }


def sweep(key, clock_sizes=SWEEP_CLOCKS, with_cost=True):
    system = SYSTEMS[key]
    x = np.linalg.solve(system.A, system.b)
    b_norm = np.linalg.norm(system.b)
    rows = []
    for n_clock in clock_sizes:
        p = parameters(system, n_clock)
        solvers = make_solvers(system, p)
        row = {"n_clock": n_clock}
        joints = {}
        for name, solver in solvers.items():
            exact = solver.exact()
            joints[name] = exact["joint"]
            out = decode(exact["joint"], p["C"], b_norm)
            row[f"rel_err_{name}"] = float(
                np.linalg.norm(out["x_abs"] - np.abs(x)) / np.linalg.norm(x))
            row[f"infidelity_{name}"] = 1 - fidelity(exact["rho1"], x)
            row[f"p_success_{name}"] = out["p_success"]
        row["rel_err"] = row["rel_err_qiskit"]
        row["framework_difference"] = float(np.max(np.abs(joints["cirq"] - joints["qiskit"])))
        if with_cost:
            row.update(solvers["qiskit"].resources())
        rows.append(row)
    return rows


def summary(record):
    p = record["params"]
    print(f"\n=== {record['title']}  ({record['key']}) ===")
    print(f"  clock qubits {p['n_clock']}, total qubits {p['qubits']}, "
          f"t = {p['t']:.5f}, C = {p['C']}, bounds [{p['lam_lo']}, {p['lam_hi']}] ({p['bounds']})")
    print("  classical x          :", np.round(record["x_classical"], 4))
    print("  HHL exact   (cirq)   :", np.round(record["exact"]["cirq"]["x_abs"], 4),
          f" fidelity {record['exact']['cirq']['fidelity']:.5f}")
    for name in ("cirq", "qiskit"):
        s = record["sampled"][name]
        print(f"  HHL sampled ({name:6s}) :", np.round(s["x_abs"], 4), "+-",
              np.round(s["x_abs_err"], 4),
              f" success {s['p_success']:.3f} ({s['accepted']} of {SHOTS} shots)")


def main():
    results = {
        "meta": {"shots": SHOTS, "seed": SEED, "python": platform.python_version(),
                 "cirq": cirq.__version__, "qiskit": qiskit.__version__,
                 "qiskit_aer": qiskit_aer.__version__, "numpy": np.__version__,
                 "scipy": scipy.__version__},
        "textbook": textbook_check(),
        "experiments": {key: run_experiment(key) for key in SYSTEMS},
        "sweep": {key: sweep(key) for key in ("coupled2", "chain4", "chain3")},
    }
    tb = results["textbook"]
    print("=== Textbook example: <X>, <Y>, <Z> of the solution qubit ===")
    rows = [("quoted in the listing", tb["expected"]), ("printed in the book", tb["printed"])]
    if tb["listing_replay"]:
        rows.append((f"original listing, mean of {tb['listing_replay']['runs']} runs",
                     tb["listing_replay"]["mean"]))
    for label, rec in (*rows,
                       ("our port, t not passed (exact)", tb["as_printed_exact"]),
                       ("our port, t passed (exact)", tb["fixed_exact"]),
                       ("our port, t passed (Cirq, sampled)", tb["fixed_sampled"]["cirq"]),
                       ("Qiskit, t passed (sampled)", tb["fixed_sampled"]["qiskit"])):
        print(f"  {label:36s}" + "  ".join(f"{axis} = {rec[axis]: .4f}" for axis in "XYZ"))
    print(f"  book output vs listing as printed: {tb['sigma_vs_as_printed']:.2f} sigma;"
          f"  vs intended values: {tb['sigma_vs_expected']:.2f} sigma")
    for record in results["experiments"].values():
        summary(record)
    print("\n=== Relative error of |x| versus number of clock qubits ===")
    for key, rows in results["sweep"].items():
        print(f"  {key:9s}", "  ".join(f"n={r['n_clock']}: {r['rel_err']:.1e}" for r in rows))

    RESULTS_FILE.parent.mkdir(exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(_plain(results), indent=1))
    print(f"\nwrote {RESULTS_FILE}")


if __name__ == "__main__":
    main()
