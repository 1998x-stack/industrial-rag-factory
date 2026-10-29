"""Stage 05: deterministic claim validation over scoped structured evidence."""
from .contracts import Claim, ClaimResult, EvidenceBundle
from .service import GroundingService
from .verifier import verify_claims

__all__ = ["Claim", "ClaimResult", "EvidenceBundle", "GroundingService", "verify_claims"]
