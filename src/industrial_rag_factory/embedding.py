"""Stage 01 dense support: offline lexical hashing or optional true multilingual embeddings."""
import hashlib
import math
import re
from collections import Counter

WORD = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


class HashingLexicalEmbedder:
    """Not semantic embeddings: only a deterministic dense lexical baseline."""
    name = "hashing-lexical-v1"

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            tokens = WORD.findall(text.lower())
            han = [t for t in tokens if len(t) == 1 and "\u4e00" <= t <= "\u9fff"]
            tokens += [han[i] + han[i + 1] for i in range(len(han) - 1)]
            vec = [0.0] * 256
            for word, n in Counter(tokens).items():
                h = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8], "big")
                vec[h % 256] += 1 + math.log(n)
            norm = math.sqrt(sum(v*v for v in vec)) or 1
            vectors.append([v/norm for v in vec])
        return vectors


class SentenceTransformerEmbedder:
    def __init__(self, model: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install industrial-rag-factory[dense]") from exc
        self.name = model
        self.model = SentenceTransformer(model)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


def create_embedder(backend: str, model: str):
    if backend == "none":
        return None
    if backend == "hashing":
        return HashingLexicalEmbedder()
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    raise ValueError("Unknown embedding backend")
