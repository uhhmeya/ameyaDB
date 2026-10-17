import numpy as np
import pytest

import hhl_common as hc

def test_gershgorin_bounds_of_two_block_system_are_1_and_4():
    lo, hi = hc.gershgorin_bounds(hc.SYSTEMS["coupled2"].A)
    assert (lo, hi) == (1.0, 4.0)


@pytest.mark.parametrize("name", list(hc.SYSTEMS))
def test_gershgorin_bounds_contain_every_eigenvalue(name):
    A = hc.SYSTEMS[name].A
    lo, hi = hc.gershgorin_bounds(A)
    eig = np.linalg.eigvalsh(A)
    assert lo <= eig.min() and eig.max() <= hi


def test_evolution_time_puts_upper_bound_on_last_clock_value():
    n_clock, lam_hi = 5, 4.0
    t = hc.evolution_time(lam_hi, n_clock)
    lam = hc.clock_eigenvalues(n_clock, t)
    assert lam[2 ** n_clock - 1] == pytest.approx(lam_hi)


def test_clock_value_zero_is_read_as_full_turn():
    n_clock, t = 3, 0.9
    lam = hc.clock_eigenvalues(n_clock, t)
    assert lam[0] == pytest.approx(2 * np.pi / t)
    assert lam[1] == pytest.approx(2 * np.pi / (8 * t))


def test_rotation_angles_encode_C_over_lambda():
    n_clock, t, C = 4, 0.7, 0.9
    lam = hc.clock_eigenvalues(n_clock, t)
    theta = hc.rotation_angles(n_clock, t, C)
    allowed = lam >= C
    assert np.allclose(np.sin(theta[allowed] / 2), C / lam[allowed])


def test_rotation_is_switched_off_below_the_cutoff():
    n_clock, t, C = 4, 0.7, 2.0
    lam = hc.clock_eigenvalues(n_clock, t)
    theta = hc.rotation_angles(n_clock, t, C)
    assert np.any(lam < C)
    assert np.all(theta[lam < C] == 0.0)


def test_rotation_survives_rounding_when_C_sits_exactly_on_a_clock_eigenvalue():
    n_clock, t = 4, 0.7
    lam = hc.clock_eigenvalues(n_clock, t)
    theta = hc.rotation_angles(n_clock, t, C=lam[3] * (1 + 1e-13))
    assert theta[3] == pytest.approx(np.pi)


def test_decode_turns_ideal_probabilities_back_into_the_solution():
    A, b = hc.SYSTEMS["coupled2"].A, hc.SYSTEMS["coupled2"].b
    x = np.linalg.solve(A, b)
    C, b_norm = 1.0, np.linalg.norm(b)
    ok = (C / b_norm * x) ** 2
    joint = np.array([[(1 - ok.sum()) / 2] * 2, ok])
    out = hc.decode(joint, C=C, b_norm=b_norm)
    assert np.allclose(out["x_abs"], np.abs(x))
    assert out["x_norm"] == pytest.approx(np.linalg.norm(x))
    assert out["p_success"] == pytest.approx(ok.sum())


def test_decode_reports_binomial_error_bars_for_counts():
    counts = np.array([[500, 300], [150, 50]])
    out = hc.decode(counts, C=1.0, b_norm=1.0, shots=1000)
    p = 0.15
    expected = np.sqrt(p * (1 - p) / 1000) / (2 * np.sqrt(p))
    assert out["x_abs_err"][0] == pytest.approx(expected)


def test_padding_a_3x3_system_keeps_the_solution_and_adds_a_zero():
    s = hc.SYSTEMS["chain3"]
    assert s.A.shape == (4, 4) and s.n_unknowns == 3
    x = np.linalg.solve(s.A, s.b)
    assert np.allclose(x[:3], np.array([8, 3, 1]) / 21)
    assert x[3] == 0.0


import cirq
from scipy.linalg import expm

import hhl_cirq

BOOK_A = np.array([[4.30213466 - 6.01593490e-08j, 0.23531802 + 9.34386156e-01j],
                   [0.23531882 - 9.34388383e-01j, 0.58386534 + 6.01593489e-08j]])
BOOK_T = 0.358166 * np.pi
BOOK_PREP = [cirq.rx(1.276359), cirq.rz(1.276359)]
BOOK_EXPECTED = {"X": 0.144130, "Y": 0.413217, "Z": -0.899154}
BOOK_PRINTED = {"X": 0.21283255086071984, "Y": 0.3746130030959752,
                "Z": -0.8580246913580247}


def cirq_solver(key, n_clock=None):
    s = hc.SYSTEMS[key]
    p = hc.parameters(s, n_clock)
    return s, p, hhl_cirq.HHL(s.A, b=s.b, qpe_register_size=p["n_clock"], C=p["C"], t=p["t"])


def relative_error(out, x):
    return np.linalg.norm(out["x_abs"] - np.abs(x)) / np.linalg.norm(x)


def test_cirq_hamiltonian_gate_is_exp_minus_iAt_on_two_qubits():
    A = hc.SYSTEMS["chain4"].A
    gate = hhl_cirq.HamiltonianSimulation(A, 0.7)
    assert cirq.num_qubits(gate) == 2
    assert np.allclose(cirq.unitary(gate), expm(-1j * A * 0.7))


def test_cirq_hamiltonian_gate_power_multiplies_the_time():
    A = hc.SYSTEMS["coupled2"].A
    gate = hhl_cirq.HamiltonianSimulation(A, 0.7) ** 8
    assert np.allclose(cirq.unitary(gate), expm(-1j * A * 5.6))


def test_cirq_qft_uses_the_textbook_sign_convention():
    qubits = cirq.LineQubit.range(3)
    qft = hhl_cirq.QFT(qubits)
    N = 8
    dft = np.array([[np.exp(-2j * np.pi * x * y / N) for x in range(N)]
                    for y in range(N)]) / np.sqrt(N)
    assert np.allclose(cirq.unitary(qft.circuit), dft)
    assert np.allclose(cirq.unitary(qft.inv_circuit), dft.conj().T)


def test_cirq_phase_estimation_writes_the_eigenvalue_into_the_clock():
    memory = [cirq.LineQubit(2)]
    clock = cirq.LineQubit.range(2)
    U = hhl_cirq.HamiltonianSimulation(np.diag([1.0, 2.0]), np.pi / 2)
    qpe = hhl_cirq.QuantumPhaseEstimation(U, input_qubits=memory, output_qubits=clock)
    circuit = cirq.Circuit(cirq.X(memory[0])) + qpe.circuit
    state = cirq.Simulator().simulate(circuit, qubit_order=clock + memory).final_state_vector
    probs = np.abs(state.reshape(4, 2)) ** 2
    assert probs[2, 1] == pytest.approx(1.0, abs=1e-6)


def test_cirq_eigenvalue_inversion_uses_the_lookup_angle_of_each_clock_value():
    n_clock, t, C = 3, 0.7, 2.0
    theta = hc.rotation_angles(n_clock, t, C)
    assert np.any(theta == 0.0) and np.any(theta > 0.0)
    clock = cirq.LineQubit.range(1, n_clock + 1)
    ancilla = cirq.LineQubit(0)
    gate = hhl_cirq.EigenValueInversion(n_clock + 1, C, t)
    for k in range(2 ** n_clock):
        bits = [(k >> (n_clock - 1 - j)) & 1 for j in range(n_clock)]
        circuit = cirq.Circuit(cirq.X(q) for q, bit in zip(clock, bits) if bit)
        circuit.append(gate(*clock, ancilla))
        state = cirq.Simulator().simulate(
            circuit, qubit_order=[ancilla] + clock).final_state_vector
        p_one = np.sum(np.abs(state.reshape(2, -1)[1]) ** 2)
        assert p_one == pytest.approx(np.sin(theta[k] / 2) ** 2, abs=1e-6)


@pytest.mark.parametrize("b", [
    [0.6, 0.8], [0.6, -0.8], [-1.0, 2.0],
    [1.0, 2.0, 3.0, 4.0], [1.0, -2.0, 0.0, 0.5], [0.0, 0.0, -1.0, 1.0],
    [1.0, 1.0, 1.0, 0.0, -2.0, 0.5, 0.0, 3.0]])
def test_cirq_amplitude_encoding_reproduces_signed_real_vectors(b):
    b = np.array(b)
    qubits = cirq.LineQubit.range(int(np.log2(len(b))))
    circuit = cirq.Circuit(cirq.I.on_each(*qubits), hhl_cirq.amplitude_encoding(b, qubits))
    state = cirq.Simulator().simulate(circuit, qubit_order=qubits).final_state_vector
    assert np.allclose(state, b / np.linalg.norm(b), atol=1e-6)


def test_cirq_amplitude_encoding_refuses_complex_vectors():
    with pytest.raises(ValueError, match="real"):
        hhl_cirq.amplitude_encoding(np.array([1.0, 1.0j]), cirq.LineQubit.range(1))


def test_cirq_solves_the_diagonal_system_exactly():
    s, p, hhl = cirq_solver("diagonal2")
    out = hc.decode(hhl.exact()["joint"], C=p["C"], b_norm=np.linalg.norm(s.b))
    assert np.allclose(out["x_abs"], [1.0, 0.5], atol=1e-6)
    assert out["p_success"] == pytest.approx(0.625, abs=1e-6)


def test_cirq_textbook_example_gives_the_expected_observables_once_t_is_passed():
    hhl = hhl_cirq.HHL(BOOK_A, initial_state_transforms=BOOK_PREP,
                       qpe_register_size=4, t=BOOK_T)
    pauli = hc.pauli_expectations(hhl.exact()["rho1"])
    for axis in "XYZ":
        assert pauli[axis] == pytest.approx(BOOK_EXPECTED[axis], abs=1e-5)


def test_cirq_listing_with_default_t_explains_the_numbers_printed_in_the_book():
    hhl = hhl_cirq.HHL(BOOK_A, initial_state_transforms=BOOK_PREP, qpe_register_size=4)
    exact = hhl.exact()
    pauli = hc.pauli_expectations(exact["rho1"])
    accepted = 5000 * np.trace(exact["rho1"]).real
    for axis in "XYZ":
        sigma = np.sqrt((1 - pauli[axis] ** 2) / accepted)
        assert abs(pauli[axis] - BOOK_PRINTED[axis]) < sigma


def test_cirq_error_on_the_coupled_system_shrinks_with_the_clock_size():
    errors = {}
    for n_clock in (4, 8):
        s, p, hhl = cirq_solver("coupled2", n_clock)
        out = hc.decode(hhl.exact()["joint"], C=p["C"], b_norm=np.linalg.norm(s.b))
        errors[n_clock] = relative_error(out, np.linalg.solve(s.A, s.b))
    assert errors[8] < errors[4]
    assert errors[8] < 2e-3


def test_cirq_solves_the_four_block_chain():
    s, p, hhl = cirq_solver("chain4")
    exact = hhl.exact()
    out = hc.decode(exact["joint"], C=p["C"], b_norm=np.linalg.norm(s.b))
    assert np.allclose(out["x_abs"], [0.6, 0.8, 0.8, 0.6], atol=0.01)
    assert hc.fidelity(exact["rho1"], np.linalg.solve(s.A, s.b)) > 0.999


def test_cirq_padding_state_of_the_three_block_chain_is_never_populated():
    s, p, hhl = cirq_solver("chain3")
    joint = hhl.exact()["joint"]
    assert joint[:, 3].sum() == pytest.approx(0.0, abs=1e-9)


def test_cirq_sampled_counts_follow_the_exact_probabilities():
    s, p, hhl = cirq_solver("coupled2", 4)
    joint = hhl.exact()["joint"]
    shots = 20000
    counts = hhl.sample(shots, seed=7)
    assert counts.sum() == shots
    sigma = np.sqrt(joint * (1 - joint) / shots)
    assert np.all(np.abs(counts / shots - joint) < 5 * sigma)


def test_cirq_sampled_pauli_readout_matches_the_exact_one():
    hhl = hhl_cirq.HHL(BOOK_A, initial_state_transforms=BOOK_PREP,
                       qpe_register_size=4, t=BOOK_T)
    sampled = hhl.sample_pauli(20000, seed=3)
    for axis in "XYZ":
        assert sampled[axis] == pytest.approx(BOOK_EXPECTED[axis], abs=0.06)


def test_cirq_diagram_labels_the_textbook_gates_readably():
    s, p, hhl = cirq_solver("diagonal2")
    diagram = str(hhl.build_hhl_circuit())
    assert "object at 0x" not in diagram
    assert "U^2" in diagram and "Ry(C/lam_k)" in diagram


def test_cirq_clock_histogram_peaks_at_the_two_eigenvalues():
    s, p, hhl = cirq_solver("diagonal2")
    assert np.allclose(hhl.clock_distribution(), [0.0, 0.5, 0.5, 0.0], atol=1e-6)


import hhl_qiskit

BOOK_B = cirq.unitary(cirq.rz(1.276359)) @ cirq.unitary(cirq.rx(1.276359)) @ np.array([1, 0])


def qiskit_solver(key, n_clock=None):
    s = hc.SYSTEMS[key]
    p = hc.parameters(s, n_clock)
    return s, p, hhl_qiskit.HHL(s.A, s.b, n_clock=p["n_clock"], C=p["C"], t=p["t"])


def test_qiskit_phase_estimation_writes_the_eigenvalue_into_the_clock():
    solver = hhl_qiskit.HHL(np.diag([1.0, 2.0]), [0.0, 1.0], n_clock=2, C=1.0, t=np.pi / 2)
    assert np.allclose(solver.clock_distribution(), [0, 0, 1, 0], atol=1e-9)


def test_qiskit_solves_the_diagonal_system_exactly():
    s, p, solver = qiskit_solver("diagonal2")
    out = hc.decode(solver.exact()["joint"], C=p["C"], b_norm=np.linalg.norm(s.b))
    assert np.allclose(out["x_abs"], [1.0, 0.5], atol=1e-9)
    assert out["p_success"] == pytest.approx(0.625, abs=1e-9)


def test_qiskit_textbook_example_gives_the_expected_observables():
    solver = hhl_qiskit.HHL(BOOK_A, BOOK_B, n_clock=4, t=BOOK_T)
    pauli = hc.pauli_expectations(solver.exact()["rho1"])
    for axis in "XYZ":
        assert pauli[axis] == pytest.approx(BOOK_EXPECTED[axis], abs=1e-5)


def test_qiskit_solves_the_four_block_chain():
    s, p, solver = qiskit_solver("chain4")
    exact = solver.exact()
    out = hc.decode(exact["joint"], C=p["C"], b_norm=np.linalg.norm(s.b))
    assert np.allclose(out["x_abs"], [0.6, 0.8, 0.8, 0.6], atol=0.01)
    assert hc.fidelity(exact["rho1"], np.linalg.solve(s.A, s.b)) > 0.999


def test_qiskit_padding_state_of_the_three_block_chain_is_never_populated():
    s, p, solver = qiskit_solver("chain3")
    assert solver.exact()["joint"][:, 3].sum() == pytest.approx(0.0, abs=1e-9)


def test_qiskit_sampled_counts_follow_the_exact_probabilities():
    s, p, solver = qiskit_solver("coupled2", 4)
    joint = solver.exact()["joint"]
    shots = 20000
    counts = solver.sample(shots, seed=7)
    assert counts.sum() == shots
    sigma = np.sqrt(joint * (1 - joint) / shots)
    assert np.all(np.abs(counts / shots - joint) < 5 * sigma)


def test_qiskit_sampled_pauli_readout_matches_the_exact_one():
    solver = hhl_qiskit.HHL(BOOK_A, BOOK_B, n_clock=4, t=BOOK_T)
    sampled = solver.sample_pauli(20000, seed=3)
    for axis in "XYZ":
        assert sampled[axis] == pytest.approx(BOOK_EXPECTED[axis], abs=0.06)


def test_qiskit_top_level_circuit_shows_the_five_stages_as_blocks():
    s, p, solver = qiskit_solver("diagonal2")
    names = [instruction.operation.label or instruction.operation.name
             for instruction in solver.build_circuit().data]
    assert names == ["|b>", "QPE", "Ry(theta_k)", "QPE inverse"]


def test_qiskit_compiles_to_the_same_gate_sequence_every_time():
    s, p, solver = qiskit_solver("diagonal2")

    def gate_sequence():
        compiled = solver._compile(solver._measured("Y"))
        return [(inst.operation.name, [compiled.find_bit(q).index for q in inst.qubits])
                for inst in compiled.data]

    first = gate_sequence()
    assert all(gate_sequence() == first for _ in range(5))


def test_qiskit_circuit_uses_one_ancilla_plus_clock_plus_memory_qubits():
    s, p, solver = qiskit_solver("chain4")
    cost = solver.resources()
    assert cost["qubits"] == 1 + p["n_clock"] + 2
    assert cost["cx"] > 0 and cost["depth"] > 0


@pytest.mark.parametrize("key", list(hc.SYSTEMS))
def test_cirq_and_qiskit_give_the_same_exact_statistics(key):
    _, _, a = cirq_solver(key)
    _, _, b = qiskit_solver(key)
    ea, eb = a.exact(), b.exact()
    assert np.allclose(ea["joint"], eb["joint"], atol=1e-7)
    assert np.allclose(ea["rho1"], eb["rho1"], atol=1e-7)
    assert np.allclose(a.clock_distribution(), b.clock_distribution(), atol=1e-7)


def numpy_model_of_hhl(A, b, n_clock, t, C):
    N = 2 ** n_clock
    lam, vectors = np.linalg.eigh(A)
    beta = vectors.conj().T @ (np.asarray(b, dtype=complex) / np.linalg.norm(b))
    y = np.arange(N)
    fourier = np.exp(2j * np.pi * np.outer(y, y) / N) / np.sqrt(N)
    hadamard = (-1.0) ** np.array([[bin(a & c).count("1") for c in y] for a in y]) / np.sqrt(N)
    amplitude = np.sin(hc.rotation_angles(n_clock, t, C) / 2)
    clock = []
    for eigenvalue in lam:
        kick = np.exp(1j * eigenvalue * t * y)
        after_qpe = fourier.conj().T @ (kick * hadamard[:, 0])
        clock.append(hadamard @ (kick.conj() * (fourier @ (amplitude * after_qpe))))
    state = sum(beta[j] * np.outer(clock[j], vectors[:, j]) for j in range(len(lam)))
    return np.sum(np.abs(state) ** 2, axis=0)


@pytest.mark.parametrize("key", list(hc.SYSTEMS))
def test_both_frameworks_match_an_independent_numpy_model(key):
    s, p, a = cirq_solver(key)
    _, _, b = qiskit_solver(key)
    expected = numpy_model_of_hhl(s.A, s.b, p["n_clock"], p["t"], p["C"])
    assert np.allclose(a.exact()["joint"][1], expected, atol=1e-7)
    assert np.allclose(b.exact()["joint"][1], expected, atol=1e-7)


def test_cirq_and_qiskit_agree_on_the_textbook_example():
    a = hhl_cirq.HHL(BOOK_A, initial_state_transforms=BOOK_PREP, qpe_register_size=4, t=BOOK_T)
    b = hhl_qiskit.HHL(BOOK_A, BOOK_B, n_clock=4, t=BOOK_T)
    assert np.allclose(a.exact()["rho1"], b.exact()["rho1"], atol=1e-7)


import run_experiments


def test_experiment_record_holds_the_classical_answer_and_both_frameworks():
    record = run_experiments.run_experiment("diagonal2", shots=2000, seed=5)
    assert np.allclose(record["x_classical"], [1.0, 0.5])
    assert record["framework_difference"] < 1e-9
    for framework in ("cirq", "qiskit"):
        assert np.allclose(record["exact"][framework]["x_abs"], [1.0, 0.5], atol=1e-6)
        sampled = record["sampled"][framework]
        assert np.all(np.abs(np.array(sampled["x_abs"]) - [1.0, 0.5])
                      < 5 * np.array(sampled["x_abs_err"]))
        assert set(record["pauli"]["sampled"][framework]) >= {"X", "Y", "Z"}


def test_textbook_check_separates_the_printed_listing_from_the_fixed_one():
    check = run_experiments.textbook_check(shots=2000, seed=5, replay_runs=20)
    assert check["sigma_vs_as_printed"] < 1.0 < check["sigma_vs_expected"]
    assert check["fixed_exact"]["Z"] == pytest.approx(-0.899154, abs=1e-5)
    assert check["printed_accepted"] == {"X": 1278, "Y": 1292, "Z": 1296}
    replay = check["listing_replay"]
    assert replay["runs"] == 20
    for axis in "XYZ":
        assert abs(replay["mean"][axis] - check["as_printed_exact"][axis]) < 5 * replay["sem"][axis]


def test_sweep_error_decreases_from_small_to_large_clock():
    rows = run_experiments.sweep("coupled2", [3, 8], with_cost=False)
    assert rows[1]["rel_err"] < rows[0]["rel_err"]
    assert all(row["framework_difference"] < 1e-9 for row in rows)


import textbook_replay


def test_unmodified_listing_prints_the_values_of_the_t_equals_one_circuit():
    printed = textbook_replay.run_listing_once()
    as_printed = hhl_cirq.HHL(BOOK_A, initial_state_transforms=BOOK_PREP, qpe_register_size=4)
    exact = as_printed.exact()
    pauli = hc.pauli_expectations(exact["rho1"])
    accepted = 5000 * np.trace(exact["rho1"]).real
    for axis in "XYZ":
        sigma = np.sqrt((1 - pauli[axis] ** 2) / accepted)
        assert abs(printed[axis] - pauli[axis]) < 5 * sigma


def test_listing_replay_is_reproducible_with_a_seed():
    first = textbook_replay.replay(runs=2, seed=11)
    second = textbook_replay.replay(runs=2, seed=11)
    assert first["mean"] == second["mean"]
