"""Document-level ranking metrics, citation integrity and cautious answer coverage."""
from __future__ import annotations

import math
from collections import defaultdict

from industrial_rag_factory.experiments.stats import cluster_bootstrap_ci


def score(retrieved: list[str], relevant: set[str], k: int) -> dict:
    if not relevant or k<1:
        raise ValueError("Nonempty relevance and positive k required")
    ranked=list(dict.fromkeys(retrieved))[:k]
    positions=[i+1 for i,uri in enumerate(ranked) if uri in relevant]
    # Each public record currently has exactly one benchmark-provided context.
    return {"recall":len(positions)/len(relevant),
            "hit":float(bool(positions)),
            "mrr":1/min(positions) if positions else 0.,
            "ndcg":sum(1/math.log2(rank+1) for rank in positions) /
                   sum(1/math.log2(i+2) for i in range(min(k,len(relevant))))}


def summarize(rows: list[dict], *, resamples: int = 300) -> dict:
    output={}
    for split in ("train","dev","test"):
        current=[x for x in rows if x["split"]==split]
        if not current:
            raise ValueError("Missing required split")
        metrics={name:sum(x[name] for x in current)/len(current)
                 for name in ("recall","hit","mrr","ndcg")}
        metrics["cases"]=len(current)
        metrics["groups"]=len({x["group_id"] for x in current})
        if split=="test":
            for metric in ("recall","mrr","ndcg"):
                if metrics["groups"]>=2:
                    metrics[metric+"_ci"]=cluster_bootstrap_ci(
                        [{"id":r["id"],"group_id":r["group_id"],metric:r[metric]}
                         for r in current],metric,resamples=resamples,seed=2921)
        output[split]=metrics
    domains=defaultdict(list)
    for row in rows:
        if row["split"]=="test":
            domains[row["industry"]].append(row)
    output["test_by_industry"]={
        name:{"n":len(group),"hit_at_k":sum(x["hit"] for x in group)/len(group)}
        for name,group in sorted(domains.items())
    }
    return output
