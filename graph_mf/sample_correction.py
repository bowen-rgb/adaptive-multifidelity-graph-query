"""Independent gain fitting and empirical seed-level calibration for COUNTs."""
import math
from statistics import mean


def fit_profile(fitting, calibration, levels, countries, fingerprint, alpha=.1):
    if not 0 < alpha < 1 or not fitting or not calibration:
        raise ValueError('Nonempty independent splits and alpha in (0,1) required')
    fit_seeds = {r['seed'] for r in fitting}
    cal_seeds = {r['seed'] for r in calibration}
    if fit_seeds & cal_seeds:
        raise ValueError('Fitting and calibration seeds must be disjoint')
    rank = math.ceil((len(cal_seeds)+1)*(1-alpha))
    if rank > len(cal_seeds):
        raise ValueError('Insufficient independent calibration seeds')
    expected = {(seed,country,kind,f) for seed in fit_seeds|cal_seeds
                for country in countries for kind in ('node','edge') for f in levels}
    actual = [(r['seed'],r['country'],r['kind'],r['fidelity']) for r in fitting+calibration]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError('Complete, unique split measurements required')
    components = []
    for kind,power in [('node',1),('edge',2)]:
        for f in levels:
            rows = [r for r in fitting if r['kind']==kind and r['fidelity']==f]
            estimates = [(r['count']/f**power,r['truth']) for r in rows]
            denominator = sum(x*x for x,y in estimates)
            gain = sum(x*y for x,y in estimates)/denominator if denominator else 1.
            if f==1:
                gain=1.
            entry = dict(kind=kind,fidelity=f,gain=gain,
                         forecast_ms=mean(r['query_ms'] for r in rows),
                         reference_sample_count=mean(r['count'] for r in rows))
            for name,g in [('raw',1.),('corrected',gain)]:
                scores = [max(abs(g*r['count']/f**power-r['truth'])/max(r['truth'],1)
                    for r in calibration if r['seed']==seed and r['kind']==kind and r['fidelity']==f)
                    for seed in sorted(cal_seeds)]
                entry[name+'_bound']=sorted(scores)[rank-1]
                normalized = [max(abs(g*r['count']/f**power-r['truth'])/max(r['truth'],1)
                    / math.sqrt(max(entry['reference_sample_count'],1)/max(r['count'],1))
                    for r in calibration if r['seed']==seed and r['kind']==kind and r['fidelity']==f)
                    for seed in sorted(cal_seeds)]
                entry[name+'_count_score']=sorted(normalized)[rank-1]
            components.append(entry)
    return dict(graph_sha256=fingerprint,countries=list(countries),levels=list(levels),
                fit_seeds=sorted(fit_seeds),calibration_seeds=sorted(cal_seeds),alpha=alpha,
                components=components,scope='empirical static-graph bounds per component/level; selection and joint coverage are not guaranteed')


def answer(profile, backend, country, kind, tolerance, corrected=True, gated=True, fixed=.25):
    if not math.isfinite(tolerance) or tolerance < 0 or kind not in ('node','edge'):
        raise ValueError('Finite nonnegative tolerance and known component required')
    if backend.graph.fingerprint != profile['graph_sha256']:
        raise ValueError('Calibration graph changed')
    rows = [r for r in profile['components'] if r['kind']==kind]
    name = 'corrected' if corrected else 'raw'
    fallback = gated and country not in profile['countries']
    candidates = [r for r in rows if r[name+'_bound'] <= tolerance] if gated else [r for r in rows if r['fidelity']==fixed]
    row = next(r for r in rows if r['fidelity']==1) if fallback else min(candidates,key=lambda r:r['forecast_ms']) if candidates else next(r for r in rows if r['fidelity']==1)
    result = backend.count_component(country,row['fidelity'],kind)
    query_ms=result['query_ms']; attempts=1
    # A sparse realization was not made reliable by fitting a multiplicative gain.
    if gated and row['fidelity'] < 1 and result['count'] < 20:
        row=next(r for r in rows if r['fidelity']==1)
        result=backend.count_component(country,1,kind)
        query_ms+=result['query_ms']; attempts+=1; fallback=True
    f=row['fidelity']; power=1 if kind=='node' else 2
    estimate=result['count']/f**power * (row['gain'] if corrected else 1)
    return dict(estimate=estimate,fidelity=f,bound=row[name+'_bound'],query_ms=query_ms,
                attempts=attempts,fallback=fallback,raw_count=result['count'])


class DynamicSampler:
    """Probe then escalate using a calibrated, count-adjusted empirical uncertainty.

    This score is not a per-request probabilistic confidence interval. Especially
    for correlated edge inclusion, calibration transfer requires empirical checks.
    """
    def __init__(self, profile, backend, corrected=True, min_count=20):
        if backend.graph.fingerprint != profile['graph_sha256']:
            raise ValueError('Calibration graph changed')
        self.profile, self.backend = profile, backend
        self.corrected, self.min_count = corrected, min_count

    def request(self, country, kind, tolerance):
        if kind not in ('node','edge') or not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError('Known component and finite nonnegative tolerance required')
        if self.backend.graph.fingerprint != self.profile['graph_sha256']:
            raise ValueError('Calibration graph changed')
        rows=sorted((r for r in self.profile['components'] if r['kind']==kind),key=lambda r:r['fidelity'])
        unknown=country not in self.profile['countries']
        if unknown or tolerance==0:
            rows=[r for r in rows if r['fidelity']==1]
        trace=[]; query_ms=0.
        for row in rows:
            f=row['fidelity']; result=self.backend.count_component(country,f,kind)
            query_ms+=result['query_ms']
            name='corrected' if self.corrected else 'raw'
            uncertainty=row[name+'_count_score']*math.sqrt(max(row['reference_sample_count'],1)/max(result['count'],1))
            accepted=f==1 or (result['count']>=self.min_count and uncertainty<=tolerance)
            trace.append(dict(fidelity=f,raw_count=result['count'],uncertainty=uncertainty,
                              accepted=accepted,query_ms=result['query_ms']))
            if accepted:
                power=1 if kind=='node' else 2
                return dict(estimate=result['count']/f**power*(row['gain'] if self.corrected else 1),
                            fidelity=f,bound=uncertainty,query_ms=query_ms,attempts=len(trace),
                            fallback=unknown or f==1,raw_count=result['count'],trace=trace)
        raise ValueError('Exact terminal level required')
