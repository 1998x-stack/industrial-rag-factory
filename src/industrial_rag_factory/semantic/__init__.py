"""Stage 02: offline, read-only industrial semantic knowledge engineering."""
from .identity import EntityResolver, Resolution
from .graph import KnowledgeGraph
from .competency import evaluate_competency_questions

__all__ = ["EntityResolver", "Resolution", "KnowledgeGraph", "evaluate_competency_questions"]
