"""Validated experimental protocol, source-group holdout and leakage checks."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ALLOWED_MODES = ("sparse","dense","hybrid")
SPLITS = ("train","dev","test")
SIMPLE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: object) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",",":"),
                             ensure_ascii=False).encode("utf-8"))


def validate_config(config: dict) -> dict:
    if not isinstance(config,dict) or set(config)!={
        "version","chunk_sizes","overlaps","modes","seeds","k","bootstrap_resamples"
    } or config["version"]!="stage07-v1":
        raise ValueError("Unsupported or incomplete experimental config")
    for key,lower,upper in (("chunk_sizes",10,1000),("overlaps",0,500),
                             ("seeds",0,2**31-1)):
        values=config[key]
        if (not isinstance(values,list) or not values or len(values)>8
            or len(values)!=len(set(map(str,values)))
            or any(type(x) is not int or not lower<=x<=upper for x in values)):
            raise ValueError(f"Invalid factor: {key}")
    if min(config["chunk_sizes"])<=max(config["overlaps"]):
        raise ValueError("Every chunk/overlap combination must be feasible")
    if (not isinstance(config["modes"],list) or not config["modes"]
        or len(set(config["modes"]))!=len(config["modes"])
        or not set(config["modes"])<=set(ALLOWED_MODES)):
        raise ValueError("Invalid retrieval modes")
    if type(config["k"]) is not int or not 1<=config["k"]<=10:
        raise ValueError("Invalid top-k")
    if (type(config["bootstrap_resamples"]) is not int
        or not 100<=config["bootstrap_resamples"]<=5000):
        raise ValueError("Invalid bootstrap resample count")
    if (len(config["chunk_sizes"])*len(config["overlaps"])
        *len(config["modes"])*len(config["seeds"])>192):
        raise ValueError("Experimental run budget exceeded")
    return config


def load_cases(path: str | Path) -> list[dict]:
    path=Path(path)
    rows=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
          if line.strip()]
    if len(rows)<9:
        raise ValueError("Need >=9 independently labeled fixture questions")
    seen_ids=set()
    group_split={}
    uri_group={}
    normalized_query_split={}
    content_split={}
    by_split={s:0 for s in SPLITS}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={
            "id","split","group_id","source_uri","document_text","question"
        }:
            raise ValueError("Invalid retrieval case schema")
        ident,split,group=row["id"],row["split"],row["group_id"]
        if (not isinstance(ident,str) or not SIMPLE.fullmatch(ident)
            or ident in seen_ids or split not in SPLITS
            or not isinstance(group,str) or not SIMPLE.fullmatch(group)):
            raise ValueError("Invalid or duplicate case/split/group")
        seen_ids.add(ident)
        for key in ("source_uri","document_text","question"):
            if not isinstance(row[key],str) or not row[key].strip():
                raise ValueError(f"Missing {key}")
        if not row["source_uri"].startswith("fixture://s07/"):
            raise ValueError("Only synthetic S07 fixture sources allowed")
        if len(row["document_text"])>10000 or len(row["question"])>2000:
            raise ValueError("Oversized fixture content")
        query_key=" ".join(row["question"].casefold().split())
        content_key=digest(" ".join(row["document_text"].casefold().split()).encode())
        for lookup,key in ((group_split,group),(uri_group,row["source_uri"]),
                           (normalized_query_split,query_key),(content_split,content_key)):
            if key in lookup and lookup[key]!=split:
                raise ValueError("Data leakage: group, URI, duplicate query or document spans splits")
            lookup[key]=split
        by_split[split]+=1
    if not all(by_split[s]>=3 for s in SPLITS):
        raise ValueError("Each train/dev/test split needs >=3 cases")
    return rows


def data_fingerprint(config_path: str | Path, cases_path: str | Path) -> dict:
    return {"config_sha256":digest(Path(config_path).read_bytes()),
            "cases_sha256":digest(Path(cases_path).read_bytes())}
