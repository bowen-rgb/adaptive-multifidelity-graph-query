"""IC5 CSV oracle and offline sampling-quality study, not database performance.

Eligible friendships/memberships stay exact; Post ranks are reproducible and
shared across every query in a sampling epoch. Each Post must have one creator
and one containing forum in this supported generator format.
"""
import csv
import random
import re
from pathlib import Path
from .synthetic import numpy
from .ldbc_full import filesystem_path,file_sha256


class IC5Offline:
    def __init__(self, people, forums, titles, posts, creators, containers, friendships, memberships):
        np=numpy()
        self.people=np.asarray(people,dtype=np.int64);self.forums=np.asarray(forums,dtype=np.int64)
        self.posts=np.asarray(posts,dtype=np.int64);self.titles=titles
        for ids in (self.people,self.forums,self.posts):
            if not (np.diff(ids)>0).all():raise ValueError('Sorted unique IDs required')
        self.adj=[set() for _ in people]
        for a,b in friendships:
            self.adj[int(a)].add(int(b));self.adj[int(b)].add(int(a))
        self.members=np.asarray(memberships,dtype=np.int64).reshape(-1,3)
        creators=np.asarray(creators,dtype=np.int64);containers=np.asarray(containers,dtype=np.int64)
        if len(creators)!=len(posts) or len(containers)!=len(posts) or (creators<0).any() or (containers<0).any():
            raise ValueError('Every post needs one creator and one containing forum')
        self.codes=containers*len(people)+creators
        self.order=np.argsort(self.codes,kind='stable');self.sorted_codes=self.codes[self.order]
        self.eligibility={}

    def prefixes(self,seed,levels):
        np=numpy();rng=random.Random(seed)
        ranks=np.fromiter((rng.random() for _ in self.posts),dtype=np.float64,count=len(self.posts))[self.order]
        return {f:np.concatenate(([0],np.cumsum(ranks<f,dtype=np.int64))) for f in levels}

    def counts(self,person_id,min_date,fidelity=1.,prefixes=None):
        np=numpy();root=int(np.searchsorted(self.people,person_id))
        if root>=len(self.people) or self.people[root]!=person_id:return [],[]
        cache_key=(person_id,min_date)
        if cache_key not in self.eligibility:
            friends=set(self.adj[root])
            for friend in self.adj[root]:friends.update(self.adj[friend])
            friends.discard(root)
            valid=np.zeros(len(self.people),dtype=bool)
            if friends:valid[list(friends)]=True
            selected=self.members[valid[self.members[:,1]] & (self.members[:,2]>min_date)]
            if not len(selected):return [],[]
            keys=np.unique(selected[:,0]*len(self.people)+selected[:,1]);forums=np.unique(selected[:,0])
            lower=np.searchsorted(self.sorted_codes,keys,side='left');upper=np.searchsorted(self.sorted_codes,keys,side='right')
            # Static eligibility only; every seed still recomputes sampled counts.
            # This oracle has no database performance role.
            self.eligibility[cache_key]=(keys,forums,lower,upper)
        keys,forums,lower,upper=self.eligibility[cache_key]
        if fidelity==1:contributions=upper-lower
        else:
            if not 0<fidelity<1 or prefixes is None or fidelity not in prefixes:raise ValueError('Attached nested prefix required')
            contributions=prefixes[fidelity][upper]-prefixes[fidelity][lower]
        totals=np.bincount(keys//len(self.people),weights=contributions,minlength=len(self.forums))
        if fidelity!=1:totals=totals/fidelity
        order=np.lexsort((self.forums[forums],-totals[forums]));chosen=forums[order]
        return chosen,totals

    def query(self,person_id,min_date,fidelity=1.,prefixes=None,limit=20):
        chosen,totals=self.counts(person_id,min_date,fidelity,prefixes)
        return [dict(forumId=int(self.forums[i]),forumName=self.titles[int(i)],
                     postCount=int(totals[i]) if fidelity==1 else float(totals[i])) for i in chosen[:limit]]


def load_ic5_csv(root):
    np=numpy();root=filesystem_path(root);manifest=[]
    def rows(stem):
        pattern=re.compile(re.escape(stem)+r'_\d+_\d+\.csv$')
        files=sorted(path for path in (root/'dynamic').glob(stem+'_*.csv') if pattern.fullmatch(path.name))
        if not files:raise ValueError('Required table missing: '+stem)
        for path in files:
            count=0
            with path.open(encoding='utf-8',newline='') as handle:
                reader=csv.reader(handle,delimiter='|');next(reader)
                for row in reader:count+=1;yield row
            manifest.append(dict(table=stem,file=path.name,rows=count,sha256=file_sha256(path)))
    people=np.sort(np.fromiter((int(r[0]) for r in rows('person')),dtype=np.int64))
    forum_rows=sorted((int(r[0]),r[1]) for r in rows('forum'))
    forums=np.array([r[0] for r in forum_rows],dtype=np.int64);titles=[r[1] for r in forum_rows]
    posts=np.sort(np.fromiter((int(r[0]) for r in rows('post')),dtype=np.int64))
    def index(ids,value):
        i=int(np.searchsorted(ids,value))
        if i>=len(ids) or ids[i]!=value:raise ValueError('Missing relationship endpoint')
        return i
    friendships=[(index(people,int(r[0])),index(people,int(r[1]))) for r in rows('person_knows_person')]
    memberships=[(index(forums,int(r[0])),index(people,int(r[1])),int(r[2])) for r in rows('forum_hasMember_person')]
    def post_relation(stem,post_column,other_column,other_ids):
        output=np.full(len(posts),-1,dtype=np.int64);pending=[]
        def assign():
            block=np.asarray(pending,dtype=np.int64);positions=np.searchsorted(posts,block[:,0]);others=np.searchsorted(other_ids,block[:,1])
            if (positions>=len(posts)).any() or (others>=len(other_ids)).any():raise ValueError('Missing endpoint')
            if not (posts[positions]==block[:,0]).all() or not (other_ids[others]==block[:,1]).all():raise ValueError('Missing endpoint')
            if len(np.unique(positions))!=len(positions) or (output[positions]>=0).any():raise ValueError('Duplicate post ownership')
            output[positions]=others
        for row in rows(stem):
            pending.append((int(row[post_column]),int(row[other_column])))
            if len(pending)==50000:assign();pending=[]
        if pending:assign()
        if (output<0).any():raise ValueError('Unattached post')
        return output
    creators=post_relation('post_hasCreator_person',0,1,people)
    containers=post_relation('forum_containerOf_post',1,0,forums)
    graph=IC5Offline(people,forums,titles,posts,creators,containers,friendships,memberships)
    return graph,manifest
