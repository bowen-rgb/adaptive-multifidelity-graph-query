"""DLSS-inspired calibrated aggregate scaling; no neural/image reconstruction."""
import json
import math
from pathlib import Path
from time import perf_counter
from .synthetic import SyntheticMemory, numpy

LEVELS = (0.05, 0.10, 0.15, 0.25, 0.35, 0.50, 0.75, 1.0)
COUNTRIES = ('FR', 'DE', 'ES', 'IT', 'NL')
TIERS = {'performance': (0.05, 0.15), 'balanced': (0.02, 0.05),
         'quality': (0.01, 0.02), 'exact': (0.0, 0.0)}


def calibrate(graph, fit_epochs=20, calibration_epochs=40, countries=COUNTRIES):
    """Fit gains then calibrate joint max residuals over countries, levels and metrics.

    The seed epoch is the independent unit. This avoids treating five correlated
    country queries sharing a rank vector as five independent calibration samples.
    All predicates/levels are fixed in advance; held-out seeds are never used here.
    Bounds are empirical on this static graph, not guarantees under distribution shift.
    """
    if fit_epochs < 2 or calibration_epochs < 20:
        raise ValueError('Use >=2 fitting epochs and >=20 calibration epochs')
    np = numpy()
    backend = SyntheticMemory(graph)
    truth = {c: backend.counts(c) for c in countries}
    fit_seeds = list(range(2000, 2000 + fit_epochs))
    calibration_seeds = list(range(3000, 3000 + calibration_epochs))
    if set(fit_seeds) & set(calibration_seeds):
        raise ValueError('Fitting/calibration seeds must be disjoint')
    examples = {f: {kind: [] for kind in ('node', 'edge')} for f in LEVELS}
    start = perf_counter()
    for seed in fit_seeds:
        backend.prepare(seed)
        for country in countries:
            for f in LEVELS:
                counts = backend.counts(country, f)
                for kind, power in (('node', 1), ('edge', 2)):
                    examples[f][kind].append((counts[kind + '_count'] / f**power,
                                              truth[country][kind + '_count']))
    levels = []
    for f in LEVELS:
        row = dict(fidelity=f)
        for kind in ('node', 'edge'):
            pairs = examples[f][kind]
            denominator = sum(x*x for x, y in pairs)
            gain = sum(x*y for x, y in pairs) / denominator if denominator else 1.0
            gain = 1.0 if f == 1 else gain
            scale = math.sqrt(sum(((gain*x-y)/max(y, 1))**2 for x, y in pairs) / len(pairs))
            row[kind + '_gain'] = gain
            row[kind + '_scale'] = 0.0 if f == 1 else max(scale, 1e-9)
        levels.append(row)
    scores = []
    for seed in calibration_seeds:
        backend.prepare(seed)
        score = 0.0
        for country in countries:
            for row in levels[:-1]:
                f = row['fidelity']
                counts = backend.counts(country, f)
                for kind, power in (('node', 1), ('edge', 2)):
                    predicted = row[kind + '_gain'] * counts[kind + '_count'] / f**power
                    actual = truth[country][kind + '_count']
                    residual = abs(predicted-actual) / max(actual, 1)
                    score = max(score, residual / row[kind + '_scale'])
        scores.append(score)
    # Split-calibration order statistic; no formal coverage claim for changed workloads.
    rank = math.ceil((len(scores) + 1) * 0.95)
    q = sorted(scores)[rank - 1]
    for row in levels:
        for kind in ('node', 'edge'):
            row[kind + '_bound'] = q * row[kind + '_scale']
    return dict(algorithm='calibrated-aggregate-scaling-v1', graph_sha256=graph.fingerprint,
        countries=list(countries), levels=levels, tiers=TIERS,
        fitting_seeds=fit_seeds, calibration_seeds=calibration_seeds,
        calibration_scores=scores, joint_quantile=q, target_coverage=0.95,
        calibration_unit='one seed: max residual across all countries, levels and both metrics',
        calibration_cpu_ms=1000 * (perf_counter() - start),
        coverage_scope='empirical static-graph seed variation; not a guarantee under workload shift',
        sample_algorithm='numpy-default_rng-uniform-v1')


def save_profile(path, profile):
    Path(path).write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')


class AdaptiveController:
    def __init__(self, profile, demotion_patience=3, min_nodes=20, min_edges=10,
                 cost_policy='amortized'):
        if demotion_patience < 1 or min_nodes < 0 or min_edges < 0:
            raise ValueError('Invalid hysteresis/minimum count configuration')
        if cost_policy not in ('amortized', 'cached'):
            raise ValueError('Cost policy must be amortized or cached')
        self.cost_policy = cost_policy
        if (profile.get('algorithm') != 'calibrated-aggregate-scaling-v1'
                or [r['fidelity'] for r in profile['levels']] != list(LEVELS)):
            raise ValueError('Unsupported calibration profile')
        for row in profile['levels']:
            for kind in ('node', 'edge'):
                if any(not math.isfinite(row[kind + suffix]) or row[kind + suffix] < 0
                       for suffix in ('_gain', '_bound')):
                    raise ValueError('Invalid correction or uncertainty bound')
                if row['fidelity'] == 1 and (row[kind + '_gain'] != 1 or row[kind + '_bound'] != 0):
                    raise ValueError('Exact level must have identity correction and zero bound')
        self.profile = profile
        self.patience, self.min_nodes, self.min_edges = demotion_patience, min_nodes, min_edges
        self.scope, self.current, self.pending, self.streak = None, None, None, 0

    def request(self, cache, country='FR', tier='balanced', budgets=None, reuse_requests=100):
        start = perf_counter()
        if tier not in TIERS:
            raise ValueError('Unknown tier')
        budgets = TIERS[tier] if budgets is None else budgets
        if len(budgets) != 2 or any(not math.isfinite(b) or b < 0 for b in budgets) or reuse_requests < 1:
            raise ValueError('Use finite nonnegative node/edge budgets and positive reuse count')
        identity = (cache.fingerprint, country,
                    cache.active_state['generation'] if cache.active_state else None)
        if identity != self.scope:
            self.scope, self.current, self.pending, self.streak = identity, None, None, 0
        compatible = (cache.fingerprint == self.profile['graph_sha256']
                      and country in self.profile['countries'])
        levels = self.profile['levels']

        def eligible(row):
            return row['node_bound'] <= budgets[0] and row['edge_bound'] <= budgets[1]

        def cost(row):
            timing = self.profile.get('timing', {}).get(country, {}).get(str(row['fidelity']))
            if timing:
                return timing['request_ms_mean'] + (self.profile.get('build_ms_mean', 0) / reuse_requests
                    if row['fidelity'] < 1 and self.cost_policy == 'amortized' else 0)
            return row['fidelity']

        feasible = [r for r in levels if eligible(r)] if compatible else [levels[-1]]
        desired = min(feasible, key=cost)['fidelity']
        if not compatible or all(b == 0 for b in budgets):
            selected = 1.0
        elif self.current is None:
            selected = LEVELS[0]  # Charge the initial low-fidelity draft and any escalation.
        elif desired > self.current:
            selected = desired
            self.pending, self.streak = None, 0
        elif desired < self.current:
            self.streak = self.streak + 1 if self.pending == desired else 1
            self.pending = desired
            selected = desired if self.streak >= self.patience else self.current
        else:
            selected = self.current
            self.pending, self.streak = None, 0
        steps = []
        while True:
            row = next(r for r in levels if r['fidelity'] == selected)
            observed = cache.counts(country, selected)
            steps.append(dict(fidelity=selected, request_ms=observed['request_ms'],
                              node_count=observed['node_count'], edge_count=observed['edge_count']))
            enough = observed['node_count'] >= self.min_nodes and observed['edge_count'] >= self.min_edges
            if selected == 1 or (eligible(row) and enough):
                break
            higher = [r for r in levels if r['fidelity'] > selected and eligible(r)]
            selected = min(higher, key=cost)['fidelity'] if higher else 1.0
        previous = self.current
        self.current = selected
        result = dict(tier=tier, country=country, fidelity=selected, cost_policy=self.cost_policy,
            desired_fidelity=desired, node_budget=budgets[0], edge_budget=budgets[1],
            compatible_profile=compatible, changed=previous is not None and previous != selected,
            steps=steps, queries=len(steps),
            raw_node_estimate=observed['node_count'] / selected,
            raw_edge_estimate=observed['edge_count'] / selected**2,
            node_estimate=row['node_gain'] * observed['node_count'] / selected,
            edge_estimate=row['edge_gain'] * observed['edge_count'] / selected**2,
            node_bound=row['node_bound'], edge_bound=row['edge_bound'])
        for kind in ('node', 'edge'):
            predicted, bound = result[kind + '_estimate'], result[kind + '_bound']
            result[kind + '_interval'] = ([predicted / (1 + bound), predicted / (1 - bound)]
                                          if bound < 1 else [0.0, None])
        result['request_ms'] = 1000 * (perf_counter() - start)
        return result
