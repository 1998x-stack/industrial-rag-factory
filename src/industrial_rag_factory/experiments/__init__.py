"""Stage 07 experiment API; avoid expensive ontology/DB imports for metrics only."""
from .contracts import load_cases, validate_config
from .stats import cluster_bootstrap_ci, paired_cluster_delta_ci


def run_factory(*args, **kwargs):
    """Load Stage 07 full stack only for actual cross-stage experiments."""
    from .runner import run_factory as execute
    return execute(*args, **kwargs)


__all__ = ["load_cases", "validate_config", "cluster_bootstrap_ci",
           "paired_cluster_delta_ci", "run_factory"]
