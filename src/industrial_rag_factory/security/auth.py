"""Local-only HMAC capability token demonstration; never an enterprise login system."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from .policy import AccessDenied, PolicyStore, Principal

AUDIENCE="industrial-rag-factory-s06-demo"
MAX_TTL=900


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text + "="*((-len(text))%4),altchars=b"-_",validate=True)


class TokenVerifier:
    def __init__(self, secret: str, policy: PolicyStore):
        if not isinstance(secret,str) or len(secret.encode("utf-8"))<32:
            raise ValueError("S06 demo secret must contain at least 32 UTF-8 bytes")
        self.secret=secret.encode("utf-8")
        self.policy=policy

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self.secret,("s06."+payload).encode("ascii"),
                             hashlib.sha256).digest())

    def authenticate(self, authorization: str | None, *, now: int | None = None) -> Principal:
        if not isinstance(authorization,str) or not authorization.startswith("Bearer "):
            raise AccessDenied("Missing Bearer token")
        token=authorization[7:]
        if len(token)>2048:
            raise AccessDenied("Token too large")
        try:
            head,payload,tag=token.split(".")
            if head!="s06" or not hmac.compare_digest(self._sign(payload),tag):
                raise AccessDenied("Invalid token signature")
            data=json.loads(_unb64(payload))
            if not isinstance(data,dict) or set(data)!={"aud","sub","iat","exp","gen"}:
                raise AccessDenied("Invalid token claims")
            clock=int(time.time()) if now is None else now
            if (data["aud"]!=AUDIENCE or
                any(type(data[k]) is not int for k in ("iat","exp","gen")) or
                not data["iat"]<=clock<data["exp"] or
                data["exp"]-data["iat"]>MAX_TTL):
                raise AccessDenied("Expired or invalid capability")
            principal=self.policy.get(data["sub"])
            if data["gen"]!=principal.generation:
                raise AccessDenied("Revoked capability generation")
            return principal
        except (ValueError,TypeError,KeyError,UnicodeError,OverflowError,IndexError) as exc:
            raise AccessDenied("Invalid capability encoding") from exc


def mint_demo_token(verifier: TokenVerifier, subject: str, *,
                    ttl_seconds: int = 300, now: int | None = None) -> str:
    """Only a trusted local test/administrator helper, NEVER a public API route."""
    if type(ttl_seconds) is not int or not 1<=ttl_seconds<=MAX_TTL:
        raise ValueError("Token TTL outside allowed range")
    principal=verifier.policy.get(subject)
    clock=int(time.time()) if now is None else now
    data={"aud":AUDIENCE,"sub":subject,"iat":clock,
          "exp":clock+ttl_seconds,"gen":principal.generation}
    payload=_b64(json.dumps(data,sort_keys=True,separators=(",",":")).encode("utf-8"))
    return "s06."+payload+"."+verifier._sign(payload)
