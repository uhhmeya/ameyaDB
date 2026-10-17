import numpy as np
import cirq
from qiskit.circuit.library import HGate, IGate, XGate, RYGate
import swap_cirq
import swap_qs

SEED = 2026
THETA = float(2*np.arccos(2**-0.25))

EXPERIMENTS = [
    dict(label="E1", phi_1="|11>", phi_2="|00>", overlap_sq=0.0,
         cirq=([cirq.X], [cirq.I]), qiskit=([XGate()], [IGate()])),
    dict(label="E2", phi_1="|++>", phi_2="|++>", overlap_sq=1.0,
         cirq=([cirq.H], [cirq.H]), qiskit=([HGate()], [HGate()])),
    dict(label="E3", phi_1=f"Ry({THETA:.4f})|0> (x) Ry({THETA:.4f})|0>", phi_2="|00>", overlap_sq=0.5,
         cirq=([cirq.ry(THETA)], [cirq.I]), qiskit=([RYGate(THETA)], [IGate()])),
]

IMPLEMENTATIONS = [("cirq", "Cirq", swap_cirq), ("qiskit", "Qiskit", swap_qs)]


def run():
    for key, title, module in IMPLEMENTATIONS:
        np.random.seed(SEED)
        print()
        print("=" * 72)
        print(f"{title} implementation ({module.__name__}.py), numpy seed {SEED}")
        print("=" * 72)
        for exp in EXPERIMENTS:
            transforms_1, transforms_2 = exp[key]
            overlap_sq = exp["overlap_sq"]
            print()
            print(f"--- {exp['label']}: |phi1> = {exp['phi_1']}   |phi2> = {exp['phi_2']}")
            print(f"--- theory: |<phi1|phi2>|^2 = {overlap_sq}   |<phi1|phi2>| = {np.sqrt(overlap_sq):.4f}"
                  f"   P(0) = {(1 + overlap_sq)/2}")
            module.main(input_1_transforms=transforms_1, input_2_transforms=transforms_2)


if __name__ == '__main__':
    run()
