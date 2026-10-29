"""Minimal POSIX local audit: HMAC chained, privacy-minimized JSONL events.

This is NOT immutable storage, a SIEM, or a distributed secure audit service.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path


def _canon(item: dict) -> bytes:
    return json.dumps(item,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")


class AuditTrail:
    def __init__(self, path: str | Path, secret: str):
        if len(secret.encode("utf-8"))<32:
            raise ValueError("Audit secret length too short")
        self.path=Path(path)
        self.key=secret.encode("utf-8")

    def _tag(self, payload: dict) -> str:
        return hmac.new(self.key,_canon(payload),hashlib.sha256).hexdigest()

    def verify(self) -> bool:
        if not self.path.exists():
            return True
        previous="0"*64
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row=json.loads(line)
                tag=row.pop("tag")
                if row["previous_tag"]!=previous or not hmac.compare_digest(
                    tag,self._tag(row)
                ):
                    return False
                previous=tag
            return True
        except (OSError,ValueError,KeyError,TypeError):
            return False

    def append(self, *, subject: str, action: str, outcome: str,
               request_id: str | None = None) -> str:
        # Events contain only a pseudonymous subject digest and an allowlisted
        # event category. No raw query, evidence value, token, or source URI.
        if action not in ("auth","agent","grounding") or outcome not in (
            "allowed","denied","error"
        ):
            raise ValueError("Invalid audit event category")
        import fcntl
        request_id=request_id or uuid.uuid4().hex
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open("a+",encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try:
                handle.seek(0)
                lines=handle.readlines()
                previous="0"*64
                for line in lines:
                    row=json.loads(line)
                    tag=row.pop("tag")
                    if row["previous_tag"]!=previous or not hmac.compare_digest(
                        tag,self._tag(row)
                    ):
                        raise RuntimeError("Audit log integrity failure")
                    previous=tag
                event={"event_id":uuid.uuid4().hex,"request_id":request_id,
                       "at_epoch":int(time.time()),
                       "subject_hash":hmac.new(self.key,subject.encode("utf-8"),
                                               hashlib.sha256).hexdigest()[:24],
                       "action":action,"outcome":outcome,"previous_tag":previous}
                tag=self._tag(event)
                handle.seek(0,os.SEEK_END)
                handle.write(json.dumps({**event,"tag":tag},sort_keys=True)+"\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        return request_id
