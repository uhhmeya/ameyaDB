import numpy as np
import qiskit
import qiskit_aer
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
from qiskit.circuit.library import HGate, IGate
from qiskit_aer import AerSimulator
print('qiskit version',qiskit.__version__)
print('qiskit-aer version',qiskit_aer.__version__)
print('numpy version',np.__version__)


class SwapTest:
    def __init__(self,prepare_input_states=None,input_state_dim=None,nq=0,measure=False,copies=1000):
        self.nq = nq
        self.prepare_input_states = prepare_input_states
        self.input_state_dim = input_state_dim
        if input_state_dim is not None:
            self.num_qubits_input_states = int(np.log2(self.input_state_dim))
            print(self.num_qubits_input_states)

        self.measure = measure
        self.copies = copies
        self.ancilla_qubit = self.nq
        self.nq += 1

        if self.prepare_input_states is not None:
            if input_state_dim is None:
                raise ValueError("Please enter a valid dimension for input states to compare")
            else:
                self.num_qubits_input_states = int(np.log2(self.input_state_dim))
                self.input_1 = list(range(self.nq, self.nq + self.num_qubits_input_states))
                self.nq += self.num_qubits_input_states
                self.input_2 = list(range(self.nq, self.nq + self.num_qubits_input_states))
                self.nq += self.num_qubits_input_states

    def build_circuit(self,input_1=None,input_2=None,input_1_transforms=None,input_2_transforms=None):

        if input_1 is not None:
            self.input_1 = input_1
        if input_2 is not None:
            self.input_2 = input_2
        num_qubits = max([self.ancilla_qubit, *self.input_1, *self.input_2]) + 1
        self.circuit = QuantumCircuit(QuantumRegister(num_qubits, 'q'))
        if input_1_transforms is not None:
            for op in input_1_transforms:
                print(op)
                print(self.input_1)
                for q in self.input_1:
                    self.circuit.append(op, [q])
        if input_2_transforms is not None:
            for op in input_2_transforms:
                for q in self.input_2:
                    self.circuit.append(op, [q])

        self.circuit.h(self.ancilla_qubit)
        for i in range(len(self.input_1)):
            self.circuit.cswap(self.ancilla_qubit, self.input_1[i], self.input_2[i])
        self.circuit.h(self.ancilla_qubit)
        if self.measure:
            self.circuit.add_register(ClassicalRegister(1, 'm'))
            self.circuit.measure(self.ancilla_qubit, 0)
        print(self.circuit)

    def simulate(self):
        sim = AerSimulator()
        job = sim.run(transpile(self.circuit, sim), shots=self.copies,
                      seed_simulator=np.random.randint(2**31))
        results = job.result().get_counts()
        prob_0 = results.get('0', 0)/self.copies
        dot_product_sq = 2*(max(prob_0 - .5,0))
        return prob_0,dot_product_sq

def main(prepare_input_states=True,input_state_dim=4,
         input_1_transforms=[HGate()],
         input_2_transforms=[IGate()],measure=True,copies=1000):
    st = SwapTest(prepare_input_states=prepare_input_states,input_state_dim=input_state_dim,measure=measure,copies=copies)
    st.build_circuit(input_1_transforms=input_1_transforms,
                     input_2_transforms=input_2_transforms)
    prob_0, dot_product_sq = st.simulate()
    print(f"Probability of zero state {prob_0}")
    print(f"Sq of Dot product  {dot_product_sq}")
    print(f"Dot product  {dot_product_sq**0.5}")

if __name__ == '__main__':
    main()
