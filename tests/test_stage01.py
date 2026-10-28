"""Stage 01 tests are offline and require no DeepSeek API key."""
from pathlib import Path
import json
import pytest

from industrial_rag_factory.chunking import chunk_document
from industrial_rag_factory.config import Settings
from industrial_rag_factory.embedding import HashingLexicalEmbedder
from industrial_rag_factory.evaluation import evaluate_jsonl
from industrial_rag_factory.parsing import from_bytes
from industrial_rag_factory.pipeline import Pipeline
from industrial_rag_factory.prompts import PROMPT_VERSION

ROOT = Path(__file__).parents[1]


def doc(text: str, uri: str = "fixture://pump.md", revision: str = "1",
        tenant: str = "demo", groups: tuple[str, ...] = ("demo-readers",)):
    return from_bytes(text.encode("utf-8"),uri,".md",revision=revision,
                      tenant_id=tenant,access_groups=groups)


@pytest.fixture
def pipeline(tmp_path):
    p = Pipeline(Settings(db_path=str(tmp_path/"test.sqlite3")))
    yield p
    p.close()


def test_parsing_identity_and_revision():
    a = doc("# Pump\n\nBearing noise")
    b = doc("# Pump\n\nBearing noise")
    c = doc("# Pump\n\nBearing noise",revision="2")
    assert a.document_id == b.document_id
    assert a.sha256 == b.sha256
    assert a.document_id != c.document_id


def test_chunk_hierarchy_and_reproducibility():
    a = doc("# Pump\n## Bearing\n\nBearing noise and inspection manual.")
    x = chunk_document(a,max_tokens=12,overlap=2)
    assert x and x == chunk_document(a,max_tokens=12,overlap=2)
    assert any("Bearing" in part.section_path for part in x)
    assert all(part.token_estimate <= 12 for part in x)


def test_fts_retrieval_and_no_evidence(pipeline):
    pipeline.ingest(doc("# Pump\n\nP-102A bearing noise maintenance instructions"))
    answer = pipeline.query("P-102A bearing noise",tenant="demo",groups=("demo-readers",))
    assert answer.status == "retrieved_not_verified"
    assert "[E1]" in answer.answer
    missing = pipeline.query("P-102A",tenant="other",groups=("demo-readers",))
    assert missing.status == "insufficient_evidence"


def test_acl_denies_wrong_group(pipeline):
    pipeline.ingest(doc("# Restricted\n\nSecretPump CODE-XY99",groups=("engineering",)))
    result = pipeline.query("CODE-XY99",tenant="demo",groups=("demo-readers",))
    assert result.status == "insufficient_evidence"
    result = pipeline.query("CODE-XY99",tenant="demo",groups=("engineering",))
    assert result.evidence


def test_revision_switch(pipeline):
    pipeline.ingest(doc("# Pump\n\nUniqueOldToken",revision="A"))
    pipeline.ingest(doc("# Pump\n\nUniqueNewToken",revision="B"))
    assert not pipeline.retriever.search("UniqueOldToken",tenant="demo",
                                         groups=("demo-readers",),mode="sparse")
    hits = pipeline.retriever.search("UniqueNewToken",tenant="demo",
                                     groups=("demo-readers",),mode="sparse")
    assert hits and hits[0].revision == "B"


def test_hybrid_ranking(pipeline):
    pipeline.ingest(doc("# Maintenance\n\nP-102A bearing noise vibration"))
    assert pipeline.retriever.search("bearing noise",tenant="demo",
                   groups=("demo-readers",),mode="sparse")
    assert pipeline.retriever.search("bearing noise",tenant="demo",
                   groups=("demo-readers",),mode="dense")
    assert pipeline.retriever.search("bearing noise",tenant="demo",
                   groups=("demo-readers",),mode="hybrid")


def test_generator_citation_allowlist(pipeline):
    class FakeGenerator:
        def generate(self,question,evidence):
            return {"answer":"A bearing maintenance note is present.",
                    "citation_ids":["E1"],"abstain":False}
    pipeline.ingest(doc("# Pump\n\nBearing noise"))
    pipeline.generator = FakeGenerator()
    output = pipeline.query("bearing noise",tenant="demo",groups=("demo-readers",))
    assert output.status == "generated_citations_checked"

    class BadGenerator:
        def generate(self,question,evidence):
            return {"answer":"Invented source","citation_ids":["E999"],"abstain":False}
    pipeline.generator = BadGenerator()
    output = pipeline.query("bearing noise",tenant="demo",groups=("demo-readers",))
    assert output.status == "validation_failed"


def test_dataset_retrieval_metrics(pipeline):
    for name in ("pump_manual.md","maintenance.md","cut_spec.md"):
        path = ROOT/"datasets"/"stage01"/name
        source = "fixture://" + name
        pipeline.ingest(from_bytes(path.read_bytes(),source,path.suffix))
    report = evaluate_jsonl(pipeline,ROOT/"datasets"/"stage01"/"gold.jsonl",
                            tenant="demo",groups=("demo-readers",),k=5)
    assert report["n"] == 3
    assert 0 <= report["recall_at_k"] <= 1
    assert 0 <= report["mrr_at_k"] <= 1


def test_invalid_and_missing():
    with pytest.raises(ValueError):
        doc("")
    with pytest.raises(ValueError):
        chunk_document(doc("abc"),max_tokens=12,overlap=12)
    assert HashingLexicalEmbedder().encode(["x"]) == HashingLexicalEmbedder().encode(["x"])
    assert PROMPT_VERSION


def test_flask_local_only(tmp_path):
    flask = pytest.importorskip("flask")
    from industrial_rag_factory.api import create_app
    settings = Settings(db_path=str(tmp_path/"flask.sqlite3"))
    app = create_app(settings)
    client = app.test_client()
    assert client.get("/healthz").status_code == 200
    assert client.post("/v1/documents",json={"source_uri":"fixture://x.md",
                       "content":"# X\nBearing pump maintenance"}).status_code == 201
    r = client.post("/v1/query",json={"question":"bearing pump"})
    assert r.status_code == 200
    assert r.json["evidence"]
    assert client.post("/v1/query",json={"question":"bearing","tenant_id":"other"}).status_code == 400
    with pytest.raises(RuntimeError):
        create_app(Settings(environment="production",db_path=str(tmp_path/"prod.sqlite3")))
