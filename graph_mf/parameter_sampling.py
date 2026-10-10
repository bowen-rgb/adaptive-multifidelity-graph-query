"""Graph-specific empirical calibration transferred to held-out range parameters.

These are custom aggregate predicates, not official SNB operations. The finite
calibration query set does not establish coverage over every possible interval.
"""
from dataclasses import dataclass
import math
from time import perf_counter

from .synthetic import SyntheticGraph, generate_graph, numpy, validate_fidelity


def topology_graph(topology, nodes=20000, seed=42):
    base=generate_graph(nodes,seed=seed)
    if topology=='uniform':return base
    if topology not in ('community','hub'):raise ValueError('Unknown topology')
    np=numpy();rng=np.random.default_rng(seed+100);m=len(base.src)
    if topology=='hub':
        weights=(np.arange(nodes)+1.)**-.8;weights/=weights.sum()
        src=rng.choice(nodes,size=m,p=weights);dst=rng.choice(nodes,size=m,p=weights)
    else:
        src=rng.integers(nodes,size=m);block=max(2,nodes//10)
        lower=(src//block)*block;upper=np.minimum(lower+block,nodes)
        local=lower+(rng.random(m)*(upper-lower)).astype(int)
        dst=np.where(rng.random(m)<.85,local,rng.integers(nodes,size=m))
    while (src==dst).any():
        bad=src==dst
        dst[bad]=rng.choice(nodes,size=int(bad.sum()),p=weights) if topology=='hub' else rng.integers(nodes,size=int(bad.sum()))
    return SyntheticGraph(base.countries,src,dst,seed,base.avg_degree)


@dataclass(frozen=True)
class RangeQuery:
    country: str
    lower: int
    upper: int

    def validate(self,nodes):
        if self.country not in ('FR','DE','ES','IT','NL') or type(self.lower)!=int or type(self.upper)!=int or not 0<=self.lower<self.upper<=nodes:
            raise ValueError('Known country and valid half-open integer range required')


class RangeCounter:
    def __init__(self,backend,sample=None):
        self.backend=backend;self.graph=backend.graph;self.sample=sample
        self.state=sample.active_state.copy() if sample and sample.active_state else None

    def count(self,query,fidelity,kind):
        query.validate(len(self.graph.countries));validate_fidelity(fidelity)
        if kind not in ('node','edge'):raise ValueError('Known COUNT kind required')
        start=perf_counter()
        if self.backend.name=='memory':
            np=numpy();ids=np.arange(len(self.graph.countries))
            target=(self.graph.countries==query.country)&(ids>=query.lower)&(ids<query.upper)
            if fidelity<1:
                if not self.state or self.backend.sample_generation!=self.state['memory_generation']:
                    raise RuntimeError('Sample generation changed')
                target &= self.backend.sample<fidelity
            count=int(target.sum()) if kind=='node' else int((target[self.graph.src]&target[self.graph.dst]).sum())
        else:
            params=dict(dataset=self.backend.dataset,country=query.country,lower=query.lower,upper=query.upper,f=fidelity)
            node='MATCH (a:MFNode {dataset:$dataset,country:$country}) WHERE a.id >= $lower AND a.id < $upper '
            if fidelity<1:node+='AND a.sample < $f '
            if kind=='node':body=node+'RETURN count(a) AS count'
            else:
                body=node+'WITH a MATCH (a)-[r:MF_EDGE {dataset:$dataset}]->(b) WHERE b.dataset=$dataset AND b.country=$country AND b.id >= $lower AND b.id < $upper '
                if fidelity<1:body+='AND b.sample < $f '
                body+='RETURN count(r) AS count'
            if fidelity<1:
                if not self.state:raise RuntimeError('Attach a sample first')
                params['generation']=self.state['generation']
                body='MATCH (s:MFMaterialization {dataset:$dataset}) WHERE s.status="ready" AND s.generation=$generation WITH s CALL { '+body+' } RETURN count'
            rows,_,_=self.backend.connection.driver.execute_query(body,parameters_=params,database_=self.backend.connection.database,routing_='r')
            if not rows:raise RuntimeError('Sample generation changed')
            count=int(rows[0]['count'])
        return dict(count=count,query_ms=1000*(perf_counter()-start))


class ParameterSampler:
    def __init__(self,profile,counter,cost_guard=False):
        if profile['graph_sha256']!=counter.graph.fingerprint:raise ValueError('Refit for changed graph')
        self.profile,self.counter=profile,counter
        self.cost_guard=cost_guard

    def request(self,query,kind,budget):
        if not math.isfinite(budget) or budget<0:raise ValueError('Finite nonnegative budget required')
        query.validate(len(self.counter.graph.countries))
        rows=sorted((r for r in self.profile['components'] if r['kind']==kind),key=lambda r:r['fidelity'])
        supported=query.country in ('FR','DE') and query.upper-query.lower>=len(self.counter.graph.countries)*.15
        feasible=[r for r in rows if r['raw_bound']<=budget]
        start=next((r['fidelity'] for r in feasible),1) if supported and budget>0 else 1
        if self.cost_guard and supported and budget>0 and feasible:
            cheapest=min(feasible,key=lambda r:r['forecast_ms'])
            exact=next(r for r in rows if r['fidelity']==1)
            start=cheapest['fidelity'] if cheapest['forecast_ms']<.9*exact['forecast_ms'] else 1
        trace=[]
        for row in rows:
            f=row['fidelity']
            if f<start:continue
            measured=self.counter.count(query,f,kind)
            bound=row['raw_count_score']*math.sqrt(max(row['reference_sample_count'],1)/max(measured['count'],1))
            accepted=f==1 or measured['count']>=20 and bound<=budget
            trace.append(dict(fidelity=f,bound=bound,accepted=accepted,**measured))
            if accepted:
                return dict(estimate=measured['count']/f**(1 if kind=='node' else 2),
                    fidelity=f,attempts=len(trace),bound=bound,raw_count=measured['count'],trace=trace,
                    parameter_transfer=supported,fallback=f==1)
        raise ValueError('Exact terminal level required')
