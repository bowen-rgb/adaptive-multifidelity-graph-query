"""Budgeted measured search; the surrogate only sees evaluated candidates."""
import random
from .optimization import nsga2
from .synthetic import numpy


def select_feasible(observations, tolerance):
    feasible = [c for c, v in observations.items() if v[1] <= tolerance]
    return min(feasible, key=lambda c: (observations[c][0], c)) if feasible else None


def search(domain, evaluate, budget, tolerance, method='surrogate', seed=0):
    if budget < 2 or budget > len(domain) or len(set(domain)) != len(domain):
        raise ValueError('Unique candidates and budget in [2, domain size] required')
    if tolerance < 0 or method not in ('random', 'nsga2', 'surrogate'):
        raise ValueError('Nonnegative tolerance and known search method required')
    rng = random.Random(seed)
    observed = {}

    def measure(candidate):
        if candidate not in observed:
            cost, error = evaluate(candidate)
            if not (cost >= 0 and error >= 0):
                raise ValueError('Nonnegative finite measurements required')
            import math
            if not math.isfinite(cost) or not math.isfinite(error):
                raise ValueError('Nonnegative finite measurements required')
            observed[candidate] = (cost, error)
        return observed[candidate]

    if method == 'random':
        for candidate in rng.sample(domain, budget):
            measure(candidate)
    elif method == 'nsga2':
        class BudgetExhausted(Exception):
            pass

        def limited(candidate):
            if candidate not in observed and len(observed) == budget:
                raise BudgetExhausted
            return measure(candidate)
        try:
            nsga2(domain, limited, population_size=min(8, len(domain)),
                  generations=200, seed=seed, mutation_rate=0.5)
        except BudgetExhausted:
            pass
    else:
        np = numpy()
        # Same prior domain information is available to every method. Exact is an
        # explicitly charged anchor, not an uncharged oracle evaluation.
        measure(max(domain))
        measure(rng.choice([c for c in domain if c not in observed]))
        while len(observed) < budget:
            remaining = [c for c in domain if c not in observed]
            x = np.array(list(observed), dtype=float)
            z = np.array(remaining, dtype=float)
            distance = ((z[:, None, :] - x[None, :, :]) ** 2).sum(axis=2)
            if len(observed) % 4 == 0:
                # Exploration prevents the local model from permanently ignoring
                # unmeasured parts of the domain.
                index = int(np.argmax(distance.min(axis=1)))
            else:
                weights = np.exp(-distance / 0.12) + 1e-12
                weights /= weights.sum(axis=1, keepdims=True)
                prediction = weights @ np.array(list(observed.values()))
                cost_scale = max(float(prediction[:, 0].max()), 1e-12)
                score = prediction[:, 0] / cost_scale + 10 * np.maximum(0, prediction[:, 1] - tolerance)
                index = int(np.argmin(score))
            measure(remaining[index])
    return dict(selected=select_feasible(observed, tolerance), observations=observed,
                evaluations=len(observed), method=method)
