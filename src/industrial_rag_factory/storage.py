"""SQLite document registry + FTS5 and small-scale vector sidecar.

Access groups are filtered in SQL before ranking, never as post-retrieval masking.
The local DB is a research baseline, not a production vector index or IAM system.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from .contracts import Chunk, Document, Hit

TOKEN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def search_tokens(text: str) -> list[str]:
    raw = TOKEN.findall(text.lower())
    han = [s for s in raw if len(s) == 1 and "\u4e00" <= s <= "\u9fff"]
    terms = raw + [han[i] + han[i + 1] for i in range(len(han)-1)]
    return list(dict.fromkeys(terms))


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
          document_id TEXT PRIMARY KEY, source_uri TEXT NOT NULL, revision TEXT NOT NULL,
          title TEXT NOT NULL, tenant_id TEXT NOT NULL, access_groups TEXT NOT NULL,
          sha256 TEXT NOT NULL, parser TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS chunks (
          chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id),
          ordinal INTEGER NOT NULL, section_path TEXT NOT NULL, text TEXT NOT NULL,
          token_estimate INTEGER NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
          chunk_id UNINDEXED, lexical, tokenize='unicode61'
        );
        CREATE TABLE IF NOT EXISTS chunk_vectors (
          chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id),
          model TEXT NOT NULL, vector TEXT NOT NULL,
          PRIMARY KEY(chunk_id, model)
        );
        CREATE INDEX IF NOT EXISTS idx_docs_source ON documents(tenant_id,source_uri,active);
        """)
        self.con.commit()

    def close(self):
        self.con.close()

    def ingest(self, doc: Document, chunks: list[Chunk], vectors: list[list[float]] | None,
               vector_model: str | None) -> None:
        if vectors is not None and (len(vectors) != len(chunks) or not vector_model):
            raise ValueError("Embedding vector count/model mismatch")
        with self.con:
            self.con.execute(
                "UPDATE documents SET active=0 WHERE tenant_id=? AND source_uri=?",
                (doc.tenant_id, doc.source_uri),
            )
            # Full idempotent replace for this document revision.
            old = [r["chunk_id"] for r in self.con.execute(
                "SELECT chunk_id FROM chunks WHERE document_id=?", (doc.document_id,)
            ).fetchall()]
            for chunk_id in old:
                self.con.execute("DELETE FROM chunk_fts WHERE chunk_id=?", (chunk_id,))
                self.con.execute("DELETE FROM chunk_vectors WHERE chunk_id=?", (chunk_id,))
            self.con.execute("DELETE FROM chunks WHERE document_id=?", (doc.document_id,))
            self.con.execute("""
                INSERT INTO documents
                (document_id,source_uri,revision,title,tenant_id,access_groups,sha256,parser,active)
                VALUES(?,?,?,?,?,?,?,?,1)
                ON CONFLICT(document_id) DO UPDATE SET
                title=excluded.title, access_groups=excluded.access_groups,
                sha256=excluded.sha256, parser=excluded.parser, active=1
            """, (doc.document_id,doc.source_uri,doc.revision,doc.title,doc.tenant_id,
                  json.dumps(doc.access_groups),doc.sha256,doc.parser))
            for i, c in enumerate(chunks):
                self.con.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", (
                    c.chunk_id,c.document_id,c.ordinal,c.section_path,c.text,c.token_estimate
                ))
                self.con.execute("INSERT INTO chunk_fts(chunk_id,lexical) VALUES (?,?)",
                                 (c.chunk_id," ".join(search_tokens(c.text))))
                if vectors is not None:
                    self.con.execute(
                        "INSERT INTO chunk_vectors(chunk_id,model,vector) VALUES(?,?,?)",
                        (c.chunk_id,vector_model,json.dumps(vectors[i])),
                    )


    def remove_source(self, tenant: str, source_uri: str) -> int:
        """Physically purge superseded source revisions, FTS and embeddings.

        Used ONLY while building a detached S08 snapshot. Deleting from a
        published index is forbidden by the release manager's immutable reads.
        """
        if not tenant or not source_uri:
            raise ValueError("Explicit tenant and source are required")
        with self.con:
            documents=[r["document_id"] for r in self.con.execute(
                "SELECT document_id FROM documents WHERE tenant_id=? AND source_uri=?",
                (tenant,source_uri))]
            for document_id in documents:
                ids=[r["chunk_id"] for r in self.con.execute(
                    "SELECT chunk_id FROM chunks WHERE document_id=?",(document_id,))]
                for cid in ids:
                    self.con.execute("DELETE FROM chunk_fts WHERE chunk_id=?",(cid,))
                    self.con.execute("DELETE FROM chunk_vectors WHERE chunk_id=?",(cid,))
                self.con.execute("DELETE FROM chunks WHERE document_id=?",(document_id,))
                self.con.execute("DELETE FROM documents WHERE document_id=?",(document_id,))
        return len(documents)

    @staticmethod
    def _access_sql(groups: tuple[str, ...]) -> str:
        if not groups:
            raise ValueError("Empty access-group scope must be rejected")
        return "EXISTS (SELECT 1 FROM json_each(d.access_groups) a WHERE a.value IN (" + (
            ",".join("?" for _ in groups)) + "))"

    def sparse(self, query: str, tenant: str, groups: tuple[str, ...],
               limit: int = 20) -> list[Hit]:
        terms = search_tokens(query)
        if not terms:
            return []
        # Terms are lexicalized and double-quoted; never concatenate raw query syntax.
        expression = " OR ".join('"' + term + '"' for term in terms[:64])
        sql = f"""
          SELECT c.*,d.source_uri,d.revision,d.title,-bm25(chunk_fts) AS rank_score
          FROM chunk_fts JOIN chunks c ON c.chunk_id=chunk_fts.chunk_id
          JOIN documents d ON d.document_id=c.document_id
          WHERE chunk_fts MATCH ? AND d.tenant_id=? AND d.active=1
          AND {self._access_sql(groups)}
          ORDER BY rank_score DESC LIMIT ?
        """
        rows = self.con.execute(sql, (expression,tenant,*groups,limit)).fetchall()
        return [self._hit(r, float(r["rank_score"]), "sparse") for r in rows]

    def vectors(self, tenant: str, groups: tuple[str, ...], model: str) -> list[tuple[Hit, list[float]]]:
        sql = f"""
          SELECT c.*,d.source_uri,d.revision,d.title,v.vector
          FROM chunk_vectors v JOIN chunks c ON v.chunk_id=c.chunk_id
          JOIN documents d ON d.document_id=c.document_id
          WHERE v.model=? AND d.tenant_id=? AND d.active=1
          AND {self._access_sql(groups)}
        """
        rows = self.con.execute(sql,(model,tenant,*groups)).fetchall()
        return [(self._hit(r,0.0,"dense"),json.loads(r["vector"])) for r in rows]

    @staticmethod
    def _hit(row: sqlite3.Row, score: float, channel: str) -> Hit:
        c = Chunk(row["chunk_id"],row["document_id"],row["ordinal"],
                  row["section_path"],row["text"],row["token_estimate"])
        return Hit(c,row["source_uri"],row["revision"],row["title"],score,(channel,))
