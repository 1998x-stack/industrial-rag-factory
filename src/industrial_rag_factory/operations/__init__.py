"""Stage 08 local, offline release management. NOT an industrial deployment agent."""
from .release import ReleaseManager, ReleaseError
from .readiness import readiness_report

__all__ = ["ReleaseManager", "ReleaseError", "readiness_report"]
