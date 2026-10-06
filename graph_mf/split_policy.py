"""Independent node/edge fidelities: common execution path for all policy baselines."""
from time import perf_counter
from .adaptive import LEVELS, TIERS
from .optimization import nondominated_sort, nsga2


def policy_scores(profile, predicate):
    levels = {r['fidelity']: r for r in profile['levels']}
    timing = profile['component_timing'][predicate]
    return {(n, e): (timing['node'][str(n)] + timing['edge'][str(e)],
                     levels[n]['node_bound'], levels[e]['edge_bound']) for n in LEVELS for e in LEVELS}


def choose(scores, budgets, domain=None):
    domain = list(scores) if domain is None else domain
    feasible = [p for p in domain if scores[p][1] <= budgets[0] and scores[p][2] <= budgets[1]]
    return min(feasible, key=lambda p: (scores[p][0], p)) if feasible else (1.0, 1.0)


def optimize_policies(profile, predicate):
    scores = policy_scores(profile, predicate)
    domain = list(scores)
    exact_front = {domain[i] for i in nondominated_sort(list(scores.values()))[0]}
    searches = [nsga2(domain, scores.__getitem__, population_size=32, generations=30, seed=s)
                for s in range(10)]
    # Predeclared seed zero supplies runtime policy; never union runs to improve selection.
    selected_front = [tuple(p) for p in searches[0]['front']]
    return scores, selected_front, [dict(seed=s,
        reference_front_size=len(exact_front), maximum_recall_at_population_size=min(32, len(exact_front))/len(exact_front),
        final_front_recall=len({tuple(p) for p in r['front']} & exact_front)/len(exact_front),
        unique_evaluations=r['unique_evaluations'], objective_requests=r['objective_requests'])
        for s, r in enumerate(searches)]


def execute_pair(cache, profile, predicate, pair, corrected=True):
    start = perf_counter()
    output = dict(node_fidelity=pair[0], edge_fidelity=pair[1], steps=[])
    for kind, f, power in (('node', pair[0], 1), ('edge', pair[1], 2)):
        observed = cache.count_component(predicate, f, kind)
        row = next(r for r in profile['levels'] if r['fidelity'] == f)
        gain = row[kind+'_gain'] if corrected else 1
        output[kind+'_estimate'] = gain*observed['count']/f**power
        output['steps'].append(dict(kind=kind, fidelity=f, **observed))
    output['request_ms'] = 1000*(perf_counter()-start)
    return output


class SplitController:
    def __init__(self, profile, patience=3):
        if patience < 1:
            raise ValueError('Positive demotion patience required')
        self.profile, self.patience = profile, patience
        self.scope, self.current = None, None
        self.pending, self.streak = [None, None], [0, 0]

    def request(self, cache, predicate, tier):
        if tier not in TIERS:
            raise ValueError('Unknown tier')
        start = perf_counter()
        scope = (cache.fingerprint, predicate,
                 cache.active_state['generation'] if cache.active_state else None)
        if scope != self.scope:
            self.scope, self.current = scope, None
            self.pending, self.streak = [None, None], [0, 0]
        compatible = cache.fingerprint == self.profile['graph_sha256'] and predicate in self.profile['countries']
        scores = policy_scores(self.profile, predicate) if compatible else {(1., 1.): (0, 0, 0)}
        desired = choose(scores, TIERS[tier])
        if not compatible or tier == 'exact':
            pair = [1., 1.]
        elif self.current is None:
            pair = [LEVELS[0], LEVELS[0]]
        else:
            pair = list(self.current)
            for i in range(2):
                if desired[i] > pair[i]:
                    pair[i], self.streak[i], self.pending[i] = desired[i], 0, None
                elif desired[i] < pair[i]:
                    self.streak[i] = self.streak[i]+1 if self.pending[i] == desired[i] else 1
                    self.pending[i] = desired[i]
                    if self.streak[i] >= self.patience:
                        pair[i] = desired[i]
                else:
                    self.pending[i], self.streak[i] = None, 0
        steps, estimates = [], {}
        levels = {r['fidelity']: r for r in self.profile['levels']}
        for i, kind in enumerate(('node', 'edge')):
            while True:
                f = pair[i]
                observed = cache.count_component(predicate, f, kind)
                steps.append(dict(kind=kind, fidelity=f, **observed))
                if f == 1 or (levels[f][kind+'_bound'] <= TIERS[tier][i]
                               and observed['count'] >= (20 if kind == 'node' else 10)):
                    break
                eligible = [g for g in LEVELS if g > f and levels[g][kind+'_bound'] <= TIERS[tier][i]]
                timing = self.profile['component_timing'][predicate][kind]
                pair[i] = min(eligible, key=lambda g: timing[str(g)]) if eligible else 1.
            estimates[kind+'_estimate'] = levels[f][kind+'_gain']*observed['count']/f**(i+1)
        self.current = tuple(pair)
        return dict(node_fidelity=pair[0], edge_fidelity=pair[1], desired=list(desired),
                    steps=steps, request_ms=1000*(perf_counter()-start), **estimates)
