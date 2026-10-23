"""TSP: depot-fixed permutations; all objectives include return to depot."""
import time
import numpy as np


def validate_matrix(matrix, n=None):
    m = np.asarray(matrix, dtype=float)
    if m.ndim != 2 or m.shape[0] != m.shape[1] or (n and m.shape != (n, n)):
        raise ValueError('Ma trận phải vuông và khớp số địa điểm.')
    if not np.isfinite(m).all() or (m < 0).any() or not np.allclose(np.diag(m), 0):
        raise ValueError('Khoảng cách phải hữu hạn, không âm, đường chéo bằng 0.')
    return m


def distances(points, mode):
    if mode == 'euclidean':
        p = np.array([[a['x'], a['y']] for a in points], float)
        return np.linalg.norm(p[:, None] - p[None, :], axis=2)
    if mode != 'haversine':
        raise ValueError('Loại khoảng cách không hợp lệ.')
    p = np.radians([[a['lat'], a['lon']] for a in points])
    d = p[:, None] - p[None, :]
    h = np.sin(d[:, :, 0]/2)**2 + np.cos(p[:, None, 0])*np.cos(p[None, :, 0])*np.sin(d[:, :, 1]/2)**2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def length(route, matrix):
    return float(sum(matrix[a, b] for a, b in zip(route, route[1:])))


def nearest(matrix, depot):
    remaining = set(range(len(matrix))) - {depot}
    route = [depot]
    while remaining:
        nxt = min(remaining, key=lambda j: (matrix[route[-1], j], j))
        remaining.remove(nxt)
        route.append(nxt)
    return route + [depot]


def ordered_crossover(a, b, rng):
    n = len(a)
    if n < 2:
        return a.copy()
    lo, hi = sorted(rng.choice(n + 1, 2, replace=False))
    child = [-1]*n
    child[lo:hi] = a[lo:hi]
    rest = iter(v for v in b if v not in child)
    return [next(rest) if v == -1 else v for v in child]


def solve(matrix, depot, algorithm, cfg, seed, progress=None):
    start = time.perf_counter()
    rng = np.random.default_rng(seed)
    nodes = np.array([i for i in range(len(matrix)) if i != depot])
    def cost(p):
        return length([depot, *map(int, p), depot], matrix)
    route = nearest(matrix, depot)
    if algorithm == 'NN':
        return dict(algorithm='NN', seed=seed, route=route, distance=length(route, matrix),
                    history=[length(route, matrix)], iterations=0, time_ms=(time.perf_counter()-start)*1000)
    count, iterations = cfg['population'], cfg['iterations']
    history = []
    best, best_cost = None, float('inf')
    if algorithm == 'GA':
        pop = [rng.permutation(nodes).tolist() for _ in range(count)]
        for step in range(iterations + 1):
            scores = np.array([cost(p) for p in pop])
            k = int(scores.argmin())
            if scores[k] < best_cost:
                best, best_cost = pop[k].copy(), float(scores[k])
            history.append(best_cost)
            if progress:
                progress(step, iterations)
            if step == iterations:
                break
            def select():
                candidates = rng.integers(count, size=3)
                return pop[min(candidates, key=lambda j: scores[j])]
            new = [best.copy()]
            while len(new) < count:
                a, b = select(), select()
                child = ordered_crossover(a, b, rng) if rng.random() < cfg['crossover'] else a.copy()
                if len(child) > 1 and rng.random() < cfg['mutation']:
                    i, j = rng.choice(len(child), 2, replace=False)
                    child[i], child[j] = child[j], child[i]
                new.append(child)
            pop = new
    elif algorithm == 'PSO':
        # Random keys: argsort maps every continuous position to a valid permutation.
        x = rng.random((count, len(nodes)))
        v = rng.uniform(-0.1, 0.1, x.shape)
        personal = x.copy()
        personal_cost = np.full(count, np.inf)
        global_pos = x[0].copy()
        for step in range(iterations + 1):
            scores = np.array([cost(nodes[np.argsort(p, kind='stable')]) for p in x])
            improved = scores < personal_cost
            personal[improved], personal_cost[improved] = x[improved], scores[improved]
            k = int(personal_cost.argmin())
            if personal_cost[k] < best_cost:
                global_pos = personal[k].copy()
                best_cost = float(personal_cost[k])
                best = nodes[np.argsort(global_pos, kind='stable')].tolist()
            history.append(best_cost)
            if progress:
                progress(step, iterations)
            if step < iterations:
                v = cfg['inertia']*v + cfg['c1']*rng.random(x.shape)*(personal-x) + cfg['c2']*rng.random(x.shape)*(global_pos-x)
                v = np.clip(v, -0.5, 0.5)
                x = np.clip(x + v, 0, 1)
    else:
        raise ValueError('Thuật toán không hợp lệ.')
    return dict(algorithm=algorithm, seed=seed, route=[depot, *best, depot], distance=best_cost,
                history=history, iterations=iterations, time_ms=(time.perf_counter()-start)*1000)
