import cirq
import numpy as np
import sympy

from hhl_common import rotation_angles


class HamiltonianSimulation(cirq.EigenGate):

    def __init__(self, _H_, t, exponent=1.0):
        cirq.EigenGate.__init__(self, exponent=exponent)
        self._H_ = np.asarray(_H_, dtype=complex)
        self.t = t
        eigen_vals, eigen_vecs = np.linalg.eigh(self._H_)
        self.eigen_components = []
        for _lambda_, vec in zip(eigen_vals, eigen_vecs.T):
            theta = -_lambda_ * t / np.pi
            _proj_ = np.outer(vec, np.conj(vec))
            self.eigen_components.append((theta, _proj_))

    def _num_qubits_(self):
        return int(np.log2(self._H_.shape[0]))

    def _with_exponent(self, exponent):
        return HamiltonianSimulation(self._H_, self.t, exponent)

    def _eigen_components(self):
        return self.eigen_components


class QFT:

    def __init__(self, qubits):
        self.qubits = list(qubits)
        n = len(self.qubits)
        self.circuit = cirq.Circuit()
        for i in range(n):
            for j in range(i):
                self.circuit.append(
                    cirq.CZ(self.qubits[j], self.qubits[i]) ** (-1.0 / 2 ** (i - j)))
            self.circuit.append(cirq.H(self.qubits[i]))
        for i in range(n // 2):
            self.circuit.append(cirq.SWAP(self.qubits[i], self.qubits[n - i - 1]))
        self.inv_circuit = cirq.inverse(self.circuit)


class ControlledUnitary(cirq.Gate):

    def __init__(self, num_qubits, num_input_qubits, U):
        self._num_qubits = num_qubits
        self.num_input_qubits = num_input_qubits
        self.num_control_qubits = num_qubits - self.num_input_qubits
        self.U = U

    def num_qubits(self):
        return self._num_qubits

    def _decompose_(self, qubits):
        qubits = list(qubits)
        input_state_qubit = qubits[:self.num_input_qubits]
        control_qubits = qubits[self.num_input_qubits:]
        for i, q in enumerate(control_qubits):
            _pow_ = 2 ** (self.num_control_qubits - i - 1)
            yield cirq.ControlledGate(self.U ** _pow_)(q, *input_state_qubit)

    def _circuit_diagram_info_(self, args):
        powers = [f"U^{2 ** (self.num_control_qubits - i - 1)}"
                  for i in range(self.num_control_qubits)]
        return ["exp(-iAt)"] * self.num_input_qubits + powers


class QuantumPhaseEstimation:

    def __init__(self, U, input_qubits, output_qubits):
        self.U = U
        self.input_qubits = list(input_qubits)
        self.output_qubits = list(output_qubits)
        self.num_input_qubits = len(self.input_qubits)
        self.num_qubits = self.num_input_qubits + len(self.output_qubits)

        self.circuit = cirq.Circuit()
        self.circuit.append(cirq.H.on_each(*self.output_qubits))
        self.circuit.append(
            ControlledUnitary(self.num_qubits, self.num_input_qubits, self.U)(
                *(self.input_qubits + self.output_qubits)))
        self.circuit += QFT(qubits=self.output_qubits).inv_circuit


class EigenValueInversion(cirq.Gate):

    def __init__(self, num_qubits, C, t):
        self._num_qubits = num_qubits
        self.C = C
        self.t = t

        self.N = 2 ** (num_qubits - 1)
        self.angles = rotation_angles(num_qubits - 1, t, C)

    def num_qubits(self):
        return self._num_qubits

    def _decompose_(self, qubits):
        base_state = self.N - 1
        for eig_val_state in range(self.N):
            if eig_val_state != 0:
                base_state = eig_val_state - 1

            qubits_to_flip = eig_val_state ^ base_state

            for q in qubits[-2::-1]:
                if qubits_to_flip % 2 == 1:
                    yield cirq.X(q)
                qubits_to_flip >>= 1

            theta = self.angles[eig_val_state]
            if theta == 0.0:
                continue

            eig_val_gate = cirq.ControlledGate(cirq.ry(theta),
                                               num_controls=self._num_qubits - 1)

            yield eig_val_gate(*qubits)

    def _circuit_diagram_info_(self, args):
        return ["k"] * (self._num_qubits - 1) + ["Ry(C/lam_k)"]


def amplitude_encoding(b, qubits):
    if np.iscomplexobj(b):
        raise ValueError("amplitude_encoding needs a real vector; prepare a complex "
                         "|b> with gates via initial_state_transforms instead")
    b = np.asarray(b, dtype=float)
    b = b / np.linalg.norm(b)
    m = len(qubits)
    ops = []
    for level in range(m):
        block = 2 ** (m - level)
        for node in range(2 ** level):
            left = b[node * block: node * block + block // 2]
            right = b[node * block + block // 2: (node + 1) * block]
            if level == m - 1:
                theta = 2 * np.arctan2(right[0], left[0])
            else:
                theta = 2 * np.arctan2(np.linalg.norm(right), np.linalg.norm(left))
            if np.isclose(theta, 0.0) or np.linalg.norm(np.r_[left, right]) == 0:
                continue
            gate = cirq.ry(theta)
            if level > 0:
                path = [(node >> (level - 1 - j)) & 1 for j in range(level)]
                gate = cirq.ControlledGate(gate, control_values=path)
            ops.append(gate(*qubits[:level + 1]))
    return ops


class HHL:

    def __init__(self, hamiltonian, b=None, initial_state_transforms=None,
                 qpe_register_size=4, C=None, t=1):
        self.hamiltonian = np.asarray(hamiltonian, dtype=complex)
        self.b = b
        self.initial_state_transforms = initial_state_transforms
        self.qpe_register_size = qpe_register_size
        self.t = t
        self.C = C
        if self.C is None:
            self.C = 2 * np.pi / (2 ** self.qpe_register_size * t)

        self.ancilla_qubit = cirq.LineQubit(0)
        self.qpe_register = [cirq.LineQubit(i)
                             for i in range(1, self.qpe_register_size + 1)]
        self.initial_state_size = int(np.log2(self.hamiltonian.shape[0]))
        self.memory = [cirq.LineQubit(i)
                       for i in range(self.qpe_register_size + 1,
                                      self.qpe_register_size + 1 + self.initial_state_size)]

    def _state_preparation(self):
        if self.initial_state_transforms is not None:
            return [op(self.memory[0]) for op in self.initial_state_transforms]
        return amplitude_encoding(self.b, self.memory)

    def _phase_estimation(self):

        self.U = HamiltonianSimulation(_H_=self.hamiltonian, t=self.t)

        return QuantumPhaseEstimation(input_qubits=self.memory,
                                      output_qubits=self.qpe_register, U=self.U)

    def build_hhl_circuit(self):
        _qpe_ = self._phase_estimation()
        self.circuit = cirq.Circuit()
        self.circuit.append(self._state_preparation())
        self.circuit += _qpe_.circuit

        _eig_val_inv_ = EigenValueInversion(num_qubits=self.qpe_register_size + 1,
                                            C=self.C, t=self.t)
        self.circuit.append(_eig_val_inv_(*(self.qpe_register + [self.ancilla_qubit])))

        self.circuit += cirq.inverse(_qpe_.circuit)
        return self.circuit

    def exact(self):
        order = [self.ancilla_qubit] + self.qpe_register + self.memory
        state = cirq.Simulator(dtype=np.complex128).simulate(
            self.build_hhl_circuit(), qubit_order=order).final_state_vector
        psi = state.reshape(2, -1, 2 ** self.initial_state_size)
        joint = np.sum(np.abs(psi) ** 2, axis=1)
        rho1 = psi[1].T @ psi[1].conj()
        return {"joint": joint, "rho1": rho1}

    def clock_distribution(self):
        circuit = cirq.Circuit(self._state_preparation()) + self._phase_estimation().circuit
        state = cirq.Simulator(dtype=np.complex128).simulate(
            circuit, qubit_order=self.qpe_register + self.memory).final_state_vector
        return np.sum(np.abs(state.reshape(2 ** self.qpe_register_size, -1)) ** 2, axis=1)

    def sample(self, shots, seed=None):
        circuit = self.build_hhl_circuit().copy()
        circuit.append(cirq.measure(self.ancilla_qubit, key='a'))
        circuit.append(cirq.measure(*self.memory, key='m'))
        result = cirq.Simulator(seed=seed).run(circuit, repetitions=shots)
        a = result.measurements['a'][:, 0]
        bits = result.measurements['m']
        index = bits @ (1 << np.arange(self.initial_state_size)[::-1])
        counts = np.zeros((2, 2 ** self.initial_state_size), dtype=int)
        np.add.at(counts, (a, index), 1)
        return counts

    def sample_pauli(self, shots, seed=None):
        circuit = self.build_hhl_circuit().copy()
        circuit.append(cirq.measure(self.ancilla_qubit, key='a'))
        circuit.append([
            cirq.PhasedXPowGate(
                exponent=sympy.Symbol('exponent'),
                phase_exponent=sympy.Symbol('phase_exponent'))(*self.memory),
            cirq.measure(*self.memory, key='m')
        ])

        params = [{'exponent': 0.5, 'phase_exponent': -0.5},
                  {'exponent': 0.5, 'phase_exponent': 0},
                  {'exponent': 0, 'phase_exponent': 0}]
        results = cirq.Simulator(seed=seed).run_sweep(circuit, params, repetitions=shots)
        out = {"accepted": {}}
        for label, result in zip(('X', 'Y', 'Z'), list(results)):

            kept = result.measurements['m'][result.measurements['a'] == 1]
            out[label] = float(1 - 2 * np.mean(kept))
            out["accepted"][label] = int(len(kept))
        return out


if __name__ == '__main__':
    A = np.array([[4.30213466 - 6.01593490e-08j, 0.23531802 + 9.34386156e-01j],
                  [0.23531882 - 9.34388383e-01j, 0.58386534 + 6.01593489e-08j]])
    t = 0.358166 * np.pi
    initial_state_transforms = [cirq.rx(1.276359), cirq.rz(1.276359)]
    _hhl_ = HHL(hamiltonian=A, initial_state_transforms=initial_state_transforms,
                qpe_register_size=4, t=t)
    print(_hhl_.build_hhl_circuit())
    print("Expected observable outputs: X = 0.144130, Y = 0.413217, Z = -0.899154")
    print("Actual:", _hhl_.sample_pauli(5000, seed=1))
