import contextlib
import io
import re
import runpy
import sys
import types
from pathlib import Path

import cirq
import numpy as np

import hhl_cirq

LISTING = Path(__file__).resolve().parent.parent / "textbook_listing"


class _SingleQubitGate(cirq.Gate):

    def _num_qubits_(self):
        return 1

class _QFT(hhl_cirq.QFT):

    def qft_circuit(self):
        pass


def run_listing_once():
    cirq.SingleQubitGate = _SingleQubitGate
    sys.modules["quantum_fourier_transform"] = types.SimpleNamespace(QFT=_QFT)
    for name in ("hamiltonian_simulator", "QuantumPhaseEstimation", "EigenValueInversion"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(LISTING))
    try:
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            runpy.run_path(str(LISTING / "HHL.py"), run_name="__main__")
    finally:
        sys.path.remove(str(LISTING))
    return {axis: float(value)
            for axis, value in re.findall(r"^([XYZ]) = (\S+)$", printed.getvalue(), re.M)}


def replay(runs=20, seed=None):
    if seed is not None:
        np.random.seed(seed)
    values = np.array([[out[axis] for axis in "XYZ"]
                       for out in (run_listing_once() for _ in range(runs))])
    mean = values.mean(axis=0)
    sem = values.std(axis=0, ddof=1) / np.sqrt(runs)
    return {"runs": runs,
            "mean": dict(zip("XYZ", mean.tolist())),
            "sem": dict(zip("XYZ", sem.tolist()))}


if __name__ == "__main__":
    result = replay()
    for axis in "XYZ":
        print(f"{axis} = {result['mean'][axis]:+.4f} +- {result['sem'][axis]:.4f}"
              f"   (mean of {result['runs']} runs of the unmodified listing)")
