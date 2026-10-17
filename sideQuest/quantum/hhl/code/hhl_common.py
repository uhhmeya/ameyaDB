from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class LinearSystem:
    key: str
    title: str
    A: np.ndarray
    b: np.ndarray
    n_unknowns: int
    n_clock: int
    bounds: tuple = None


def pad_to_power_of_two(A, b, fill):
    n = len(b)
    size = 1 << int(np.ceil(np.log2(n)))
    A_pad = fill * np.eye(size)
    A_pad[:n, :n] = A
    b_pad = np.zeros(size)
    b_pad[:n] = b
    return A_pad, b_pad


def chain(n_blocks, k_neighbour=1.0, k_anchor=1.0):
    K = (2 * k_neighbour + k_anchor) * np.eye(n_blocks)
    K -= k_neighbour * (np.eye(n_blocks, k=1) + np.eye(n_blocks, k=-1))
    return K


_A3, _b3 = pad_to_power_of_two(chain(3), np.array([1.0, 0.0, 0.0]), fill=3.0)

SYSTEMS = {
    "diagonal2": LinearSystem(
        "diagonal2", "Two uncoupled springs",
        np.diag([1.0, 2.0]), np.array([1.0, 1.0]),
        n_unknowns=2, n_clock=2, bounds=(1.0, 3.0)),
    "coupled2": LinearSystem(
        "coupled2", "Two coupled blocks",
        np.array([[2.0, -1.0], [-1.0, 3.0]]), np.array([3.0, 4.0]),
        n_unknowns=2, n_clock=6),
    "chain4": LinearSystem(
        "chain4", "Chain of four blocks",
        chain(4), np.ones(4),
        n_unknowns=4, n_clock=6),
    "chain3": LinearSystem(
        "chain3", "Chain of three blocks (padded)",
        _A3, _b3,
        n_unknowns=3, n_clock=6),
}


def gershgorin_bounds(A):
    A = np.asarray(A)
    centre = np.real(np.diag(A))
    radius = np.sum(np.abs(A), axis=1) - np.abs(np.diag(A))
    return float(np.min(centre - radius)), float(np.max(centre + radius))


def evolution_time(lam_hi, n_clock):
    N = 2 ** n_clock
    return 2 * np.pi * (N - 1) / (N * lam_hi)


def clock_eigenvalues(n_clock, t):
    N = 2 ** n_clock
    k = np.arange(N, dtype=float)
    k[0] = N
    return 2 * np.pi * k / (N * t)


def rotation_angles(n_clock, t, C):
    ratio = C / clock_eigenvalues(n_clock, t)
    theta = np.zeros_like(ratio)
    ok = ratio <= 1.0 + 1e-9
    theta[ok] = 2 * np.arcsin(np.minimum(ratio[ok], 1.0))
    return theta


def parameters(system, n_clock=None):
    n_clock = system.n_clock if n_clock is None else n_clock
    lam_lo, lam_hi = system.bounds or gershgorin_bounds(system.A)
    if lam_lo <= 0:
        raise ValueError("need a positive lower bound on the eigenvalues")
    return {"n_clock": n_clock, "lam_lo": lam_lo, "lam_hi": lam_hi,
            "t": evolution_time(lam_hi, n_clock), "C": lam_lo}


def decode(joint, C, b_norm, shots=None):
    joint = np.asarray(joint, dtype=float)
    p = joint / joint.sum()
    p_success = p[1].sum()
    scale = b_norm / C
    out = {
        "p_success": p_success,
        "prob": p[1] / p_success,
        "x_abs": scale * np.sqrt(p[1]),
        "x_norm": scale * np.sqrt(p_success),
    }
    if shots is not None:
        se = np.sqrt(p[1] * (1 - p[1]) / shots)
        with np.errstate(divide="ignore", invalid="ignore"):
            out["x_abs_err"] = np.where(p[1] > 0, scale * se / (2 * np.sqrt(p[1])), 0.0)
        out["p_success_err"] = np.sqrt(p_success * (1 - p_success) / shots)
        out["accepted"] = int(round(p_success * shots))
    return out


def fidelity(rho1, x):
    x = np.asarray(x, dtype=complex)
    x = x / np.linalg.norm(x)
    return float(np.real(x.conj() @ rho1 @ x) / np.real(np.trace(rho1)))


def pauli_expectations(rho1):
    rho = rho1 / np.trace(rho1)
    return {"X": float(2 * rho[0, 1].real),
            "Y": float(2 * rho[1, 0].imag),
            "Z": float((rho[0, 0] - rho[1, 1]).real)}
