import cirq
import numpy as np
import fire
import elapsedtimer
from elapsedtimer import ElapsedTimer
print('cirq version',cirq.__version__)
print('numpy version',np.__version__)
print('fire',fire.__version__)
print('elapsedtimer',elapsedtimer.__version__)


class QFT:

    def __init__(self, signal_length=16,
                 basis_to_transform='',
                 validate_inverse_fourier=False,
                 qubits=None):

        self.signal_length = signal_length
        self.basis_to_transform = basis_to_transform

        if qubits is None:
            self.num_qubits = int(np.log2(signal_length))
            self.qubits = [cirq.LineQubit(i) for i in range(self.num_qubits)]
        else:
            self.qubits = qubits
            self.num_qubits = len(self.qubits)

        self.qubit_index = 0
        self.input_circuit = cirq.Circuit()

        self.validate_inverse_fourier = validate_inverse_fourier
        self.circuit = cirq.Circuit()
        self.inv_circuit = cirq.Circuit()

        for k, q_s in enumerate(self.basis_to_transform):
            if int(q_s) == 1:
                self.input_circuit.append(cirq.X(self.qubits[k]))

    def qft_circuit_iter(self):

        if self.qubit_index > 0:
            for j in range(self.qubit_index):
                diff = self.qubit_index - j + 1
                rotation_to_apply = -2.0 / (2.0 ** diff)
                self.circuit.append(cirq.CZ(self.qubits[self.qubit_index],
                                            self.qubits[j]) ** rotation_to_apply)
        self.circuit.append(cirq.H(self.qubits[self.qubit_index]))
        self.qubit_index += 1

    def qft_circuit(self):

        while self.qubit_index < self.num_qubits:
            self.qft_circuit_iter()
            print(f"Circuit after processing Qubit: {self.qubit_index - 1} ")
            print(self.circuit)
        self.swap_qubits()
        print("Circuit after qubit state swap:")
        print(self.circuit)
        self.inv_circuit = cirq.inverse(self.circuit.copy())

    def swap_qubits(self):
        for i in range(self.num_qubits // 2):
            self.circuit.append(cirq.SWAP(self.qubits[i], self.qubits[self.num_qubits - i - 1]))

    def simulate_circuit(self):
        sim = cirq.Simulator()
        result = sim.simulate(self.circuit)
        return result


def main(signal_length=16,
         basis_to_transform='0000',
         validate_inverse_fourier=False):

    _qft_ = QFT(signal_length=signal_length,
                basis_to_transform=basis_to_transform,
                validate_inverse_fourier=validate_inverse_fourier)


    _qft_.qft_circuit()


    if len(_qft_.input_circuit) > 0:
        _qft_.circuit = _qft_.input_circuit + _qft_.circuit

    if _qft_.validate_inverse_fourier:
        _qft_.circuit += _qft_.inv_circuit

    print("Combined Circuit")
    print(_qft_.circuit)

    output_state = _qft_.simulate_circuit()
    print(output_state)


if __name__ == '__main__':
    with ElapsedTimer('Execute Quantum Fourier Transform'):
        fire.Fire(main)