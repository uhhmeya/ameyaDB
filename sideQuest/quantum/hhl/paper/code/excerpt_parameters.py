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
