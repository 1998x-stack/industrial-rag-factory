"""Privacy-limited operational spans; exporter configuration belongs to the host.

Only operation names, a release prefix and outcome are allowed as span metadata.
No document contents, secrets, prompts or raw source paths are sent.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from time import perf_counter


@contextmanager
def span(operation: str):
    try:
        from opentelemetry import trace
    except ImportError:
        context = nullcontext()
    else:
        context = trace.get_tracer("industrial_rag_factory.operations").start_as_current_span(
            "irf.ops." + operation, record_exception=False
        )
    with context:
        start = perf_counter()
        yield lambda: round((perf_counter() - start) * 1000, 3)
