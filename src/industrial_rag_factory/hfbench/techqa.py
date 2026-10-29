"""S10: NVIDIA TechQA public technical-document RAG benchmark.

TechQA is IT technical support, NOT plant telemetry. The source label
is_impossible is reserved for evaluation and never used as a model feature.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO="nvidia/TechQA-RAG-Eval"
SOURCE="train.json"
LICENSE="apache-2.0"
SHA=re.compile(r"^[a-f0-9]{40}$")
SPLITS=("train","dev","test")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _records(data: bytes) -> list[dict]:
    if not data or len(data)>24*1024*1024:
        raise ValueError("TechQA source size outside budget")
    text=data.decode("utf-8-sig")
    try:
        parsed=json.loads(text)
        if isinstance(parsed,list):
            rows=parsed
        elif isinstance(parsed,dict) and isinstance(parsed.get("train"),list):
            rows=parsed["train"]
        elif isinstance(parsed,dict) and isinstance(parsed.get("data"),list):
            rows=parsed["data"]
        else:
            raise ValueError("Unexpected TechQA JSON container")
    except json.JSONDecodeError:
        rows=[json.loads(line) for line in text.splitlines() if line.strip()]
    if not rows or not all(isinstance(x,dict) for x in rows):
        raise ValueError("Invalid TechQA source rows")
    return rows


def normalize_techqa(data: bytes, revision: str, *,
                     per_split_per_class: int = 10,
                     extra_corpus: int = 60) -> dict:
    if not SHA.fullmatch(revision):
        raise ValueError("Full pinned HF commit required")
    if (type(per_split_per_class) is not int or not 3<=per_split_per_class<=40
        or type(extra_corpus) is not int or not 0<=extra_corpus<=250):
        raise ValueError("Invalid sample budget")
    source_rows=_records(data)
    records=[]
    seen_ids=set()
    seen_questions=set()
    sources={}
    groups={}
    for row in source_rows:
        if not {"id","question","is_impossible","contexts"}<=set(row):
            raise ValueError("TechQA schema changed")
        ident=row["id"]
        question=row["question"]
        impossible=row["is_impossible"]
        contexts=row["contexts"]
        if (not isinstance(ident,str) or len(ident)>96 or not ident
            or not isinstance(question,str) or not 3<=len(question)<=4000
            or type(impossible) is not bool or not isinstance(contexts,list)):
            raise ValueError("Malformed TechQA question")
        if ident in seen_ids:
            raise ValueError("Duplicate TechQA ID")
        seen_ids.add(ident)
        key=" ".join(question.casefold().split())
        if key in seen_questions:
            continue
        seen_questions.add(key)
        usable=[]
        for ctx in contexts[:12]:
            if not isinstance(ctx,dict):
                raise ValueError("Malformed context")
            filename=ctx.get("filename")
            text=ctx.get("text")
            if (not isinstance(filename,str) or not filename or len(filename)>220
                or not isinstance(text,str)):
                raise ValueError("Invalid context fields")
            if text.strip() and len(text)<=25000:
                digest=_hash(text.strip())
                uri=f"hf://{REPO}@{revision}/context/{digest[:24]}"
                sources.setdefault(uri,{"source_uri":uri,"text":text.strip(),
                   "title":filename,"sha256":digest})
                usable.append(uri)
        # Cases without provided contexts are explicitly impossible. A case
        # marked answerable without a usable context cannot supply a qrel.
        if not impossible and not usable:
            continue
        # Split by context content signature for answerable questions; each
        # repeated source goes to a single partition. Unanswerable questions
        # group by their normalized question (which can still be paraphrased).
        group=("src-"+_hash(sorted(usable)[0])[:24]) if usable else (
            "neg-"+_hash(key)[:24])
        groups.setdefault(group,set()).update(usable)
        records.append({"id":ident,"question":question,"impossible":impossible,
                        "context_uris":sorted(set(usable)),"group_id":group})
    # Co-occurring contexts must have the same group. Merge overlapping
    # groups using a small connected-component union-find.
    parent={x:x for x in groups}
    def root(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]
            x=parent[x]
        return x
    owner={}
    for group,uris in groups.items():
        for uri in uris:
            if uri in owner:
                parent[root(group)]=root(owner[uri])
            else:
                owner[uri]=group
    for row in records:
        row["group_id"]=root(row["group_id"])
    # Preassigned split by connected source group: never split an index
    # source URI across train/dev/test query labels.
    for row in records:
        bucket=int(_hash(row["group_id"])[:8],16)%10
        row["split"]="train" if bucket<6 else "dev" if bucket<8 else "test"
    selected=[]
    for split in SPLITS:
        for impossible in (False,True):
            matches=[r for r in records
                     if r["split"]==split and r["impossible"]==impossible]
            matches.sort(key=lambda x:(_hash(x["id"]),x["id"]))
            selected.extend(matches[:per_split_per_class])
    if any(sum(r["split"]==s and r["impossible"]==v for r in selected)<3
           for s in SPLITS for v in (False,True)):
        raise ValueError("Not enough source-group-separated answerable/unanswerable cases")
    selected_sources={x for r in selected for x in r["context_uris"]}
    unrelated=sorted(
        (uri for uri in sources if uri not in selected_sources),
        key=lambda uri:_hash(uri))
    corpus=set(selected_sources)|set(unrelated[:extra_corpus])
    doc_rows=[sources[uri] for uri in sorted(corpus)]
    query_rows=[r for r in selected]
    return {"dataset_id":REPO,"source_file":SOURCE,"license_tag":LICENSE,
            "revision":revision,"raw_sha256":hashlib.sha256(data).hexdigest(),
            "selection":"source-component-group-hash-60-20-20-balanced",
            "docs":doc_rows,"queries":query_rows,
            "counts":{s:{"answerable":sum(r["split"]==s and not r["impossible"]
                                           for r in selected),
                         "unanswerable":sum(r["split"]==s and r["impossible"]
                                           for r in selected)} for s in SPLITS},
            "unjudged_extra_docs":min(extra_corpus,len(unrelated)),
            "limitations":[
                "Technical IT troubleshooting dataset, not real OT measurements.",
                "Answerability gold labels are not included in indexed documents.",
                "Reference contexts are authored alongside questions and incomplete qrels are possible.",
                "Unanswerable labels do not establish that no document anywhere can answer.",
            ]}


def fetch_techqa(path: str | Path, *, revision: str = "main",
                 per_split_per_class: int = 10, extra_corpus: int = 60) -> dict:
    from huggingface_hub import HfApi, hf_hub_download
    if revision!="main" and not SHA.fullmatch(revision):
        raise ValueError("Only main or pinned full commit SHA")
    card=HfApi().dataset_info(REPO,revision=revision)
    sha=str(card.sha)
    if not SHA.fullmatch(sha):
        raise ValueError("HF commit not pinned")
    metadata=card.card_data or {}
    if metadata.get("license")!=LICENSE:
        raise ValueError("Changed dataset license")
    file=hf_hub_download(repo_id=REPO,repo_type="dataset",filename=SOURCE,
                         revision=sha)
    normalized=normalize_techqa(Path(file).read_bytes(),sha,
                                per_split_per_class=per_split_per_class,
                                extra_corpus=extra_corpus)
    target=Path(path)
    if target.suffix!=".json":
        raise ValueError("Only a JSON snapshot destination allowed")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(normalized,ensure_ascii=False,indent=2),
                      encoding="utf-8")
    return {"revision":sha,"source_sha256":normalized["raw_sha256"],
            "counts":normalized["counts"],"corpus_docs":len(normalized["docs"]),
            "snapshot_path":str(target)}
