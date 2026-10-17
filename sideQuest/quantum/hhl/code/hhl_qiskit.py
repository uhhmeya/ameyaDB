# this file was written with the help of claude ai

import numpy as np
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit.circuit.library import QFTGate, StatePreparation, UCRYGate, UnitaryGate
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator
from scipy.linalg import expm

from hhl_common import rotation_angles


class HHL:

    def __init__(self, A, b, n_clock=4, C=None, t=1.0):
        A = np.asarray(A, dtype=complex)
        lower = np.tril(A, -1)
        self.A = lower + lower.conj().T + np.diag(np.diag(A).real)
        self.b = np.asarray(b, dtype=complex) / np.linalg.norm(b)
        self.n_clock = n_clock
        self.t = t
        self.C = 2 * np.pi / (2 ** n_clock * t) if C is None else C

        self.m = int(np.log2(len(self.b)))
        self.memory = QuantumRegister(self.m, "b")
        self.clock = QuantumRegister(n_clock, "clock")
        self.ancilla = QuantumRegister(1, "anc")

    def _phase_estimation(self):
        qpe = QuantumCircuit(self.memory, self.clock, name="QPE")
        qpe.h(self.clock)
        for j in range(self.n_clock):
            U = UnitaryGate(expm(1j * self.A * self.t * 2 ** j), label=f"U^{2 ** j}")
            qpe.append(U.control(1), [self.clock[j], *self.memory])
        qpe.append(QFTGate(self.n_clock).inverse(), self.clock)
        return qpe

    def build_circuit(self):
        qpe = self._phase_estimation()
        qc = QuantumCircuit(self.memory, self.clock, self.ancilla)
        qc.append(StatePreparation(self.b, label="|b>"), self.memory)
        qc.append(qpe.to_gate(label="QPE"), [*self.memory, *self.clock])
        angles = rotation_angles(self.n_clock, self.t, self.C)
        rotation = UCRYGate(list(angles))
        rotation.label = "Ry(theta_k)"
        qc.append(rotation, [self.ancilla[0], *self.clock])
        qc.append(qpe.inverse().to_gate(label="QPE inverse"), [*self.memory, *self.clock])
        return qc

    def exact(self):
        state = Statevector(self.build_circuit()).data
        psi = state.reshape(2, 2 ** self.n_clock, 2 ** self.m)
        joint = np.sum(np.abs(psi) ** 2, axis=1)
        rho1 = psi[1].T @ psi[1].conj()
        return {"joint": joint, "rho1": rho1}

    def clock_distribution(self):
        qc = QuantumCircuit(self.memory, self.clock)
        qc.append(StatePreparation(self.b, label="|b>"), self.memory)
        qc.compose(self._phase_estimation(), inplace=True)
        state = Statevector(qc).data.reshape(2 ** self.n_clock, 2 ** self.m)
        return np.sum(np.abs(state) ** 2, axis=1)

    @staticmethod
    def _compile(circuit):
        return transpile(circuit, AerSimulator(), optimization_level=0, seed_transpiler=0)

    def _run(self, circuit, shots, seed):
        backend = AerSimulator(seed_simulator=seed)
        return backend.run(self._compile(circuit), shots=shots).result().get_counts()

    def _measured(self, basis="Z"):
        qc = self.build_circuit()
        if basis == "X":
            qc.h(self.memory)
        elif basis == "Y":
            qc.sdg(self.memory)
            qc.h(self.memory)
        creg = ClassicalRegister(self.m + 1, "c")
        qc.add_register(creg)
        qc.measure([*self.memory, self.ancilla[0]], creg)
        return qc

    def sample(self, shots, seed=None):
        counts = np.zeros((2, 2 ** self.m), dtype=int)
        for bitstring, n in self._run(self._measured(), shots, seed).items():
            value = int(bitstring, 2)
            counts[value >> self.m, value & (2 ** self.m - 1)] += n
        return counts

    def sample_pauli(self, shots, seed=None):
        out = {"accepted": {}}
        for offset, basis in enumerate("XYZ"):
            run_seed = None if seed is None else seed + offset
            counts = self._run(self._measured(basis), shots, run_seed)
            zeros, ones = counts.get("10", 0), counts.get("11", 0)
            out[basis] = (zeros - ones) / (zeros + ones)
            out["accepted"][basis] = zeros + ones
        return out

    def resources(self):
        compiled = transpile(self.build_circuit(), basis_gates=["cx", "u"],
                             optimization_level=1, seed_transpiler=0)
        ops = compiled.count_ops()
        return {"qubits": compiled.num_qubits, "depth": compiled.depth(),
                "cx": int(ops.get("cx", 0)), "u": int(ops.get("u", 0))}


if __name__ == "__main__":
    from hhl_common import SYSTEMS, decode, parameters

    system = SYSTEMS["coupled2"]
    p = parameters(system)
    solver = HHL(system.A, system.b, n_clock=p["n_clock"], C=p["C"], t=p["t"])
    result = decode(solver.sample(8192, seed=1), C=p["C"],
                    b_norm=np.linalg.norm(system.b), shots=8192)
    print("classical x :", np.linalg.solve(system.A, system.b))
    print("HHL |x|     :", result["x_abs"], "+-", result["x_abs_err"])
