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
