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
