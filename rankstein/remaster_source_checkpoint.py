"""Bounded exact-campaign Pinterest source progress; never a publish proof.

Only pin identities, confined raw paths, hashes and current policy metadata are
durable. OCR/source/recipe text is not stored. Callers must re-run OCR and the
held-source guard before using any returned candidate for final composition.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from rankstein.source_image_quality import SOURCE_QUALITY_POLICY, SOURCE_QUALITY_VERSION

CHECKPOINT_VERSION = 1
MAX_CHECKPOINT_BYTES = 256 * 1024
MAX_PROCESSED_PIN_IDS = 600
MAX_CHECKPOINT_SOURCES = 15
MAX_RAW_BYTES = 32 * 1024 * 1024
MAX_CHECKPOINT_AGE_SECONDS = 24 * 60 * 60


def campaign_context_hash(context: dict) -> str:
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pin_id(value) -> str:
    value = str(value or "")
    return value if re.fullmatch(r"[0-9]{1,30}", value) else ""


def _raw_hash(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_RAW_BYTES:
        raise ValueError("invalid source file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class SourceCheckpoint:
    def __init__(self, raw_root: Path, *, domain_handle: str, pipeline_run_id: str, context: dict):
        if not all(
            re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value) for value in (domain_handle, pipeline_run_id)
        ):
            raise ValueError("invalid checkpoint identity")
        self.root = (Path(raw_root).resolve() / domain_handle / pipeline_run_id).resolve()
        self.path = self.root / "source-checkpoint.json"
        self.identity = {
            "version": CHECKPOINT_VERSION,
            "domain_handle": domain_handle,
            "pipeline_run_id": pipeline_run_id,
            "context_hash": campaign_context_hash(context),
            "policy": SOURCE_QUALITY_POLICY,
            "policy_version": SOURCE_QUALITY_VERSION,
        }

    def _source(self, value: dict, *, relative_path: bool) -> dict:
        if not isinstance(value, dict) or value.get("source") != "pinterest":
            raise ValueError("invalid source identity")
        pin_id = _pin_id(value.get("pin_id"))
        if not pin_id:
            raise ValueError("invalid Pinterest pin identity")
        raw_path = Path(str(value.get("raw_path") or ""))
        if relative_path and raw_path.is_absolute():
            raise ValueError("absolute cached path")
        path = (self.root / raw_path).resolve() if relative_path else raw_path.resolve()
        path.relative_to(self.root)
        if path.stem != pin_id or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError("source path does not bind its pin identity")
        quality = value.get("source_quality")
        source_hash = str(value.get("source_hash") or "")
        if (
            not isinstance(quality, dict)
            or quality.get("accepted") is not True
            or quality.get("policy") != SOURCE_QUALITY_POLICY
            or quality.get("version") != SOURCE_QUALITY_VERSION
            or quality.get("source_hash") != source_hash
            or not re.fullmatch(r"[a-f0-9]{64}", source_hash)
            or _raw_hash(path) != source_hash
        ):
            raise ValueError("source hash or policy mismatch")
        return {
            "pin_id": pin_id,
            "raw_path": str(path),
            "source": "pinterest",
            "source_hash": source_hash,
            "original_url": f"https://www.pinterest.com/pin/{pin_id}/",
            "source_quality": {
                "accepted": True,
                "policy": SOURCE_QUALITY_POLICY,
                "version": SOURCE_QUALITY_VERSION,
                "source_hash": source_hash,
            },
        }

    def load(self, *, excluded_pin_ids: set[str]) -> dict:
        result = {"sources": [], "processed_pin_ids": set(), "invalidated": 0}
        if not self.path.is_file():
            return result
        try:
            if self.path.stat().st_size > MAX_CHECKPOINT_BYTES:
                raise ValueError("oversized checkpoint")
            payload = json.loads(self.path.read_bytes())
            if not isinstance(payload, dict) or any(
                payload.get(key) != value for key, value in self.identity.items()
            ):
                raise ValueError("checkpoint identity mismatch")
            age = time.time() - float(payload["updated_at"])
            if age < -300 or age > MAX_CHECKPOINT_AGE_SECONDS:
                raise ValueError("expired checkpoint")
            sources = payload.get("sources")
            processed = payload.get("processed_pin_ids")
            if (
                not isinstance(sources, list)
                or len(sources) > MAX_CHECKPOINT_SOURCES
                or not isinstance(processed, list)
                or len(processed) > MAX_PROCESSED_PIN_IDS
                or any(not _pin_id(value) for value in processed)
                or len(set(processed)) != len(processed)
            ):
                raise ValueError("invalid checkpoint bounds")
            durable_ids = set(processed) - excluded_pin_ids
            seen = set()
            for item in sources:
                candidate_id = _pin_id(item.get("pin_id")) if isinstance(item, dict) else ""
                if candidate_id in excluded_pin_ids:
                    durable_ids.discard(candidate_id)
                    continue
                try:
                    source = self._source(item, relative_path=True)
                    if source["pin_id"] in seen or source["pin_id"] not in durable_ids:
                        raise ValueError("duplicate or unbound source")
                except (ValueError, OSError, TypeError):
                    result["invalidated"] += 1
                    durable_ids.discard(candidate_id)
                    continue
                seen.add(source["pin_id"])
                result["sources"].append(source)
            result["processed_pin_ids"] = durable_ids
        except (ValueError, OSError, TypeError, KeyError, OverflowError):
            return {"sources": [], "processed_pin_ids": set(), "invalidated": 1}
        return result

    def save(self, sources: list[dict], processed_pin_ids: set[str]) -> None:
        safe_sources = []
        source_ids = set()
        for value in sources[:MAX_CHECKPOINT_SOURCES]:
            try:
                source = self._source(value, relative_path=False)
                if source["pin_id"] in source_ids:
                    continue
            except (ValueError, OSError, TypeError):
                continue
            source_ids.add(source["pin_id"])
            source["raw_path"] = str(Path(source["raw_path"]).relative_to(self.root))
            # The URL is reconstructed from pin identity on load.
            source.pop("original_url", None)
            safe_sources.append(source)
        remaining_ids = sorted({_pin_id(value) for value in processed_pin_ids} - source_ids - {""})
        bounded_ids = sorted(source_ids) + remaining_ids[: MAX_PROCESSED_PIN_IDS - len(source_ids)]
        payload = {
            **self.identity,
            "updated_at": time.time(),
            "sources": safe_sources,
            "processed_pin_ids": bounded_ids,
        }
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint byte bound exceeded")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".source-checkpoint-", suffix=".tmp", dir=self.root, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
