"""IndustryBench real-data normalization with strict license, schema and splits.

The dataset authors provide gold answers and knowledge_text; this is NOT
independent evidence of industrial operational safety or ground truth.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from pathlib import Path

HF_REPO="alibaba-multimodal-industrial-ai/IndustryBench"
HF_FILE="huggingface_dataset.csv"
HF_LICENSE="mit"
COMMIT=re.compile(r"^[0-9a-f]{40}$")
TEXT_LIMIT=45000
FIELDS={"id","question","answer","knowledge_text","industry_primary","capability",
        "difficulty","question_en","answer_en"}
SPLITS=("train","dev","test")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _split(group_key: str) -> str:
    # Corpus-group stable allocation does not depend on CSV row order.
    bucket=int(_sha(group_key.encode("utf-8"))[:8],16)%10
    return "train" if bucket < 6 else "dev" if bucket < 8 else "test"


def load_industrybench_csv(data: bytes, *, revision: str,
                           limit_per_split: int = 24, distractor_docs: int = 0) -> dict:
    """Create bounded real-data retrieval manifest from pinned CSV bytes.

    All 3 partitions use documents in the searchable corpus as for BEIR.
    Only query/gold labels are partitioned. Group signatures and source
    documents cannot cross the evaluation splits.
    """
    if not COMMIT.fullmatch(revision):
        raise ValueError("Dataset must be resolved to full 40-hex commit")
    if type(distractor_docs) is not int or not 0<=distractor_docs<=300:
        raise ValueError("Invalid distractor budget")
    if (type(limit_per_split) is not int or not 4<=limit_per_split<=200
        or len(data)>40*1024*1024 or not data):
        raise ValueError("Source or sample bound exceeded")
    content=data.decode("utf-8-sig")
    reader=csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or not FIELDS <= set(reader.fieldnames):
        raise ValueError("Missing IndustryBench required fields")
    raw=[]
    ids=set()
    question_owner={}
    for row in reader:
        identifier=str(row["id"]).strip()
        if not identifier or identifier in ids or len(identifier)>64:
            raise ValueError("Missing or duplicate benchmark ID")
        ids.add(identifier)
        question=str(row["question"] or "").strip()
        answer=str(row["answer"] or "").strip()
        knowledge=str(row["knowledge_text"] or "").strip()
        if not question or not answer or not knowledge:
            continue
        if max(len(question),len(answer))>4000 or len(knowledge)>TEXT_LIMIT:
            continue
        norm=_normalize(question)
        if norm in question_owner and question_owner[norm]!=identifier:
            # Skip duplicate queries, rather than count as independently labeled.
            continue
        question_owner[norm]=identifier
        # Use content hash as canonical source ID, not source row ID:
        # repeating the same evidence doesn't inflate corpus size.
        source_hash=_sha(_normalize(knowledge).encode("utf-8"))
        cluster=_sha(_normalize(knowledge[:500]).encode("utf-8"))[:24]
        group="kb-"+cluster
        raw.append({
            "id":identifier,"question":question,"answer":answer,
            "knowledge_text":knowledge,
            "question_en":str(row["question_en"] or "").strip(),
            "answer_en":str(row["answer_en"] or "").strip(),
            "industry":str(row["industry_primary"] or "").strip(),
            "capability":str(row["capability"] or "").strip(),
            "difficulty":str(row["difficulty"] or "").strip(),
            "source_hash":source_hash,"group_id":group,"split":_split(group),
        })
    # Stable, group-preserving selection: never slice after mixing groups.
    groups=defaultdict(list)
    for row in raw:
        groups[(row["split"],row["group_id"])].append(row)
    chosen=[]
    for split in SPLITS:
        candidates=[(key,items) for key,items in groups.items() if key[0]==split]
        candidates.sort(key=lambda x:x[0][1])
        picked=0
        for _,items in candidates:
            if picked+len(items)>limit_per_split:
                continue
            chosen.extend(sorted(items,key=lambda x:x["id"]))
            picked+=len(items)
            if picked==limit_per_split:
                break
    if any(sum(row["split"]==s for row in chosen)<4 for s in SPLITS):
        raise ValueError("Not enough independent real-data groups for evaluation")
    documents={}
    queries=[]
    chosen_groups={row["group_id"] for row in chosen}
    chosen_hashes={row["source_hash"] for row in chosen}
    candidates={}
    for row in raw:
        if row["group_id"] in chosen_groups or row["source_hash"] in chosen_hashes:
            continue
        candidates.setdefault(row["source_hash"],row)
    extras=sorted(candidates.values(),
                  key=lambda x:(_sha(x["source_hash"].encode()),x["id"]))
    for row in extras[:distractor_docs]:
        uri=f"hf://{HF_REPO}@{revision}/knowledge/{row['source_hash'][:24]}"
        documents[uri]={"source_uri":uri,"text":row["knowledge_text"],
                        "sha256":_sha(row["knowledge_text"].encode("utf-8")),
                        "revision":revision,"group_id":row["group_id"],
                        "title":f"Unjudged industrial context {row['source_hash'][:12]}"}
    for row in chosen:
        uri=f"hf://{HF_REPO}@{revision}/knowledge/{row['source_hash'][:24]}"
        if uri in documents and documents[uri]["text"]!=row["knowledge_text"]:
            raise ValueError("Canonical evidence source collision")
        documents[uri]={"source_uri":uri,"text":row["knowledge_text"],
                        "sha256":_sha(row["knowledge_text"].encode("utf-8")),
                        "revision":revision,"group_id":row["group_id"],
                        "title":f"IndustryBench evidence {row['source_hash'][:12]}"}
        queries.append({
            "id":row["id"],"question":row["question"],"answer":row["answer"],
            "question_en":row["question_en"],"answer_en":row["answer_en"],
            "gold_source_uri":uri,"split":row["split"],"group_id":row["group_id"],
            "industry":row["industry"],"capability":row["capability"],
            "difficulty":row["difficulty"],
        })
    return {
        "dataset_id":HF_REPO,"license_tag":HF_LICENSE,"revision":revision,
        "source_file":HF_FILE,"raw_sha256":_sha(data),
        "selection":"content-prefix-group-stable-hash-60-20-20",
        "unjudged_distractor_docs":min(distractor_docs,len(extras)),
        "documents":sorted(documents.values(),key=lambda x:x["source_uri"]),
        "queries":sorted(queries,key=lambda x:(SPLITS.index(x["split"]),x["id"])),
        "counts":{s:sum(x["split"]==s for x in queries) for s in SPLITS},
        "limitations":[
            "Benchmark-authored knowledge_text and answers are not independently verified.",
            "Each question supplies related reference context: positive document retrieval can be artificially easy.",
            "Samples are bounded deterministic subsets of the published data, not the full benchmark.",
            "Train/dev/test hold out question labels/groups, not the searchable document corpus.",
        ],
    }


def prepare_industrybench(out: str | Path, *, revision: str = "main",
                          limit_per_split: int = 24, distractor_docs: int = 64) -> dict:
    """Explicit opt-in network fetch through pinned Hugging Face dataset revision.

    No arbitrary repo/URL parameters, remote code execution or trust_remote_code.
    """
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise RuntimeError("Install industrial-rag-factory[huggingface]") from exc
    if revision!="main" and not COMMIT.fullmatch(revision):
        raise ValueError("Use main or exact revision SHA")
    info=HfApi().dataset_info(HF_REPO,revision=revision)
    pinned=str(info.sha)
    if not COMMIT.fullmatch(pinned):
        raise ValueError("Hugging Face did not return a verified revision identifier")
    # Report license as a declaration on the dataset card, not an attestation
    # that source standards/manual excerpts are separately cleared.
    actual=(info.card_data or {}).get("license",None)
    if isinstance(actual,list):
        actual=actual[0] if len(actual)==1 else actual
    if actual!=HF_LICENSE:
        raise ValueError("Unrecognized/changed dataset license metadata")
    filepath=hf_hub_download(repo_id=HF_REPO,repo_type="dataset",
                             filename=HF_FILE,revision=pinned)
    data=Path(filepath).read_bytes()
    prepared=load_industrybench_csv(data,revision=pinned,
                                    limit_per_split=limit_per_split,
                                    distractor_docs=distractor_docs)
    target=Path(out)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.suffix!=".json":
        raise ValueError("Expected JSON snapshot output")
    target.write_text(json.dumps(prepared,ensure_ascii=False,indent=2),
                      encoding="utf-8")
    return {"path":str(target),"revision":pinned,"raw_sha256":prepared["raw_sha256"],
            "counts":prepared["counts"],"documents":len(prepared["documents"]),
            "unjudged_distractor_docs":prepared["unjudged_distractor_docs"],
            "license_tag":HF_LICENSE}
