"""Nested COUNT deltas and history-guided sampling on explicitly static epochs."""
import math
from time import perf_counter
from .sample_correction import DynamicSampler


class IncrementalCounter:
    def __init__(self, sample, country, kind):
        if kind not in ('node','edge'):
            raise ValueError('Unknown COUNT component')
        self.sample, self.country, self.kind = sample, country, kind
        self.state=sample.active_state.copy() if sample.active_state else None
        self.lower, self.count = 0., 0

    def probe(self, upper):
        if not self.lower < upper <= 1:
            raise ValueError('Nested probes must increase fidelity')
        sample=self.sample; backend=sample.backend
        start=perf_counter()
        if backend.name=='memory':
            if (self.state is None or
                    backend.sample_generation!=self.state['memory_generation']):
                raise RuntimeError('Sample generation changed')
            np=__import__('numpy')
            selected=backend.graph.countries==self.country
            ranks=backend.sample
            if self.kind=='node':
                delta=int((selected & (ranks>=self.lower) & (ranks<upper)).sum())
            else:
                g=backend.graph
                maximum=np.maximum(ranks[g.src],ranks[g.dst])
                delta=int((selected[g.src] & selected[g.dst] & (maximum>=self.lower) & (maximum<upper)).sum())
        else:
            if self.state is None:
                raise RuntimeError('Attach or build a sample first')
            params=dict(dataset=backend.dataset,country=self.country,lower=self.lower,upper=upper,
                        generation=self.state['generation'])
            guard=('MATCH (s:MFMaterialization {dataset:$dataset}) '
                   'WHERE s.status="ready" AND s.generation=$generation WITH s ')
            if self.kind=='node':
                query=guard+('CALL { MATCH (n:MFNode {dataset:$dataset,country:$country}) '
                    'WHERE n.sample >= $lower AND n.sample < $upper RETURN count(n) AS count } RETURN count')
            else:
                # New source with any selected destination, OR old source with new
                # destination: disjoint partitions, including parallel directed edges.
                query=guard+('CALL { '
                    'MATCH (a:MFNode {dataset:$dataset,country:$country}) '
                    'WHERE a.sample >= $lower AND a.sample < $upper WITH a '
                    'MATCH (a)-[r:MF_EDGE {dataset:$dataset}]->(b) '
                    'WHERE b.dataset=$dataset AND b.country=$country AND b.sample < $upper '
                    'RETURN count(r) AS part UNION ALL '
                    'MATCH (a:MFNode {dataset:$dataset,country:$country}) '
                    'WHERE a.sample < $lower WITH a '
                    'MATCH (a)-[r:MF_EDGE {dataset:$dataset}]->(b) '
                    'WHERE b.dataset=$dataset AND b.country=$country '
                    'AND b.sample >= $lower AND b.sample < $upper '
                    'RETURN count(r) AS part } RETURN s.generation AS generation, sum(part) AS count')
            records,_,_=backend.connection.driver.execute_query(query,parameters_=params,
                database_=backend.connection.database,routing_='r')
            if not records:
                raise RuntimeError('Sample generation changed')
            delta=int(records[0]['count'])
        self.lower=upper; self.count+=delta
        return dict(count=self.count,query_ms=1000*(perf_counter()-start),delta=delta)


class HistorySampler(DynamicSampler):
    """Forecasted first probe, then incremental escalation, with delayed demotion.

    No answer memoization: every request executes fresh COUNTs. The graph/profile
    fingerprint is checked once at session creation; arbitrary concurrent graph
    writes are unsupported. Rank-generation publication guards each delta query.
    """
    def __init__(self,profile,sample,corrected=False,min_count=20):
        super().__init__(profile,sample.backend,corrected,min_count)
        self.sample=sample; self.history={}

    def request(self,country,kind,tolerance):
        if kind not in ('node','edge') or not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError('Known component and finite nonnegative tolerance required')
        rows=sorted((r for r in self.profile['components'] if r['kind']==kind),key=lambda r:r['fidelity'])
        key=(country,kind); name='corrected' if self.corrected else 'raw'
        unknown=country not in self.profile['countries']
        if unknown or tolerance==0:
            selected=len(rows)-1
        elif key in self.history:
            prior=self.history[key]
            selected=prior['index']
            if prior['stable']>=3:
                selected=max(0,selected-1)
        else:
            feasible=[i for i,r in enumerate(rows) if r[name+'_bound']<=tolerance]
            selected=min(feasible,key=lambda i:rows[i]['forecast_ms']) if feasible else len(rows)-1
        trace=[]; query_ms=0.; counter=IncrementalCounter(self.sample,country,kind)
        for index in range(selected,len(rows)):
            row=rows[index]; f=row['fidelity']
            if f==1:
                # Exact terminal query discards already-paid sample work.
                result=self.backend.count_component(country,1,kind)
            else:
                result=counter.probe(f)
            query_ms+=result['query_ms']
            uncertainty=row[name+'_count_score']*math.sqrt(max(row['reference_sample_count'],1)/max(result['count'],1))
            accepted=f==1 or (result['count']>=self.min_count and uncertainty<=tolerance)
            trace.append(dict(fidelity=f,raw_count=result['count'],uncertainty=uncertainty,
                              accepted=accepted,query_ms=result['query_ms']))
            if accepted:
                prior=self.history.get(key,{})
                stable=(prior.get('stable',0)+1 if prior.get('index')==index else 1) if uncertainty<=tolerance*.6 else 0
                self.history[key]=dict(index=index,stable=stable)
                power=1 if kind=='node' else 2
                return dict(estimate=result['count']/f**power*(row['gain'] if self.corrected else 1),
                            fidelity=f,bound=uncertainty,query_ms=query_ms,attempts=len(trace),
                            fallback=unknown or f==1,raw_count=result['count'],trace=trace)
        raise ValueError('Exact terminal level required')
