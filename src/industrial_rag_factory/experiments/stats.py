"""Cluster-aware percentile bootstrap with paired, shared resamples."""
from __future__ import annotations

import math
import random
from collections import defaultdict


def _groups(rows: list[dict], metric: str) -> dict[str, list[float]]:
    grouped: dict[str,list[float]]=defaultdict(list)
    for row in rows:
        value=row.get(metric)
        if (not isinstance(row.get("id"),str) or
            not isinstance(row.get("group_id"),str) or
            type(value) not in (int,float) or not math.isfinite(value) or
            not 0<=value<=1):
            raise ValueError("Invalid case metric / group identifier")
        grouped[row["group_id"]].append(float(value))
    if len(grouped)<2:
        raise ValueError("Need at least two independently sampled groups")
    return dict(grouped)


def _percentile(values: list[float], fraction: float) -> float:
    ordered=sorted(values)
    position=(len(ordered)-1)*fraction
    left=int(position)
    weight=position-left
    return ordered[left]*(1-weight)+ordered[min(left+1,len(ordered)-1)]*weight


def cluster_bootstrap_ci(rows: list[dict], metric: str, *,
                         resamples: int = 1000, seed: int = 47) -> dict:
    if not 100<=resamples<=5000:
        raise ValueError("Bootstrap resamples must be 100..5000")
    groups=_groups(rows,metric)
    names=sorted(groups)
    rng=random.Random(seed)
    estimates=[]
    for _ in range(resamples):
        chosen=[groups[names[rng.randrange(len(names))]] for _ in names]
        flat=[x for block in chosen for x in block]
        estimates.append(sum(flat)/len(flat))
    point=sum(row[metric] for row in rows)/len(rows)
    return {"estimate":point,"lower":_percentile(estimates,.025),
            "upper":_percentile(estimates,.975),"confidence":.95,
            "resamples":resamples,"independent_groups":len(names),
            "unit":"source_group","method":"percentile_cluster_bootstrap"}


def paired_cluster_delta_ci(a: list[dict], b: list[dict], metric: str, *,
                            resamples: int = 1000, seed: int = 47) -> dict:
    """Delta = configuration A - configuration B; align case IDs before sampling."""
    ia={x["id"]:x for x in a}
    ib={x["id"]:x for x in b}
    if len(ia)!=len(a) or len(ib)!=len(b) or set(ia)!=set(ib):
        raise ValueError("Paired runs must contain the same unique case IDs")
    paired=[]
    for name in sorted(ia):
        aa,bb=ia[name],ib[name]
        if aa["group_id"]!=bb["group_id"]:
            raise ValueError("Paired group mismatch")
        diff=aa[metric]-bb[metric]
        paired.append({"id":name,"group_id":aa["group_id"],"delta":(diff+1)/2})
    ci=cluster_bootstrap_ci(paired,"delta",resamples=resamples,seed=seed)
    return {**ci,"estimate":2*ci["estimate"]-1,
            "lower":2*ci["lower"]-1,"upper":2*ci["upper"]-1,
            "metric":metric,"contrast":"A_minus_B","paired":True}
