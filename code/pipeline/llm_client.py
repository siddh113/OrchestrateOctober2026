from __future__ import annotations
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore

from pipeline import LLMUsage


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO_ROOT / ".llm_cache"

_SONNET = "claude-sonnet-4-6"
_HAIKU = "claude-haiku-4-5"

# Pricing per 1M tokens (first-party API rates)
_PRICING = {
    _SONNET: {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    _HAIKU:  {"input": 0.80, "output": 4.00,  "cache_write": 1.00, "cache_read": 0.10},
}


class UsageTracker:
    _instance: Optional["UsageTracker"] = None

    def __init__(self) -> None:
        self._records: list[LLMUsage] = []

    @classmethod
    def get(cls) -> "UsageTracker":
        if cls._instance is None:
            cls._instance = UsageTracker()
        return cls._instance

    def record(self, usage: LLMUsage) -> None:
        self._records.append(usage)

    def summary(self) -> str:
        if not self._records:
            return "No LLM calls made."
        total_cost = sum(r.cost_usd for r in self._records)
        total_in = sum(r.input_tokens for r in self._records)
        total_out = sum(r.output_tokens for r in self._records)
        total_cache_read = sum(r.cache_read_tokens for r in self._records)
        total_cache_write = sum(r.cache_creation_tokens for r in self._records)
        calls = len(self._records)
        lines = [
            f"LLM calls: {calls}",
            f"Input tokens: {total_in}",
            f"Output tokens: {total_out}",
            f"Cache read tokens: {total_cache_read}",
            f"Cache write tokens: {total_cache_write}",
            f"Total cost: ${total_cost:.4f}",
            f"Avg cost/call: ${total_cost/calls:.4f}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        total_cost = sum(r.cost_usd for r in self._records)
        return {
            "calls": len(self._records),
            "total_cost_usd": total_cost,
            "records": [
                {
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "cache_read_tokens": r.cache_read_tokens,
                    "cache_creation_tokens": r.cache_creation_tokens,
                    "cost_usd": r.cost_usd,
                }
                for r in self._records
            ],
        }


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _cache_key(fn_name: str, content_sha: str) -> str:
    return hashlib.sha256(f"{fn_name}:{content_sha}".encode()).hexdigest()


def _load_cache(key: str) -> Optional[str]:
    path = _CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))["result"]
        except Exception:
            return None
    return None


def _save_cache(key: str, result: str) -> None:
    _CACHE_DIR.mkdir(exist_ok=True)
    (_CACHE_DIR / f"{key}.json").write_text(
        json.dumps({"result": result}), encoding="utf-8"
    )


def _get_client() -> "anthropic.Anthropic":
    if anthropic is None:
        raise RuntimeError("anthropic package not installed")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    return anthropic.Anthropic()


def _compute_cost(model: str, usage) -> float:
    p = _PRICING.get(model, {"input": 3.0, "output": 15.0, "cache_write": 0.0, "cache_read": 0.0})
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    cr_tok = getattr(usage, "cache_read_input_tokens", 0) or 0
    cw_tok = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        in_tok * p["input"] / 1_000_000
        + out_tok * p["output"] / 1_000_000
        + cr_tok * p["cache_read"] / 1_000_000
        + cw_tok * p["cache_write"] / 1_000_000
    )


def _record_usage(model: str, usage) -> None:
    lu = LLMUsage(
        model=model,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cost_usd=_compute_cost(model, usage),
    )
    UsageTracker.get().record(lu)


def extract_pdf(file_path: str) -> str:
    """Extract text/facts from a PDF evidence file. Returns extracted text."""
    file_sha = _sha256_file(file_path)
    key = _cache_key("extract_pdf", file_sha)
    cached = _load_cache(key)
    if cached is not None:
        return cached

    with open(file_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("ascii")

    client = _get_client()
    response = client.messages.create(
        model=_SONNET,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": (
                    "You are a data extraction assistant. Extract ALL factual information "
                    "from this document: names, emails, user IDs, resource IDs, system names, "
                    "dates, statuses, and any identifiers. Output as plain structured text. "
                    "Be complete and literal."
                ),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                    },
                    {"type": "text", "text": "Extract all factual information from this document."},
                ],
            }
        ],
    )
    result = response.content[0].text
    _record_usage(_SONNET, response.usage)
    _save_cache(key, result)
    return result


def extract_image(file_path: str) -> str:
    """Extract text/facts from a PNG screenshot. Returns extracted text."""
    file_sha = _sha256_file(file_path)
    key = _cache_key("extract_image", file_sha)
    cached = _load_cache(key)
    if cached is not None:
        return cached

    with open(file_path, "rb") as f:
        img_data = base64.standard_b64encode(f.read()).decode("ascii")

    # Detect media type
    ext = Path(file_path).suffix.lower()
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
        ext, "image/png"
    )

    client = _get_client()
    response = client.messages.create(
        model=_SONNET,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": (
                    "You are a data extraction assistant. Extract ALL factual information "
                    "from this image: names, emails, user IDs, resource IDs, system names, "
                    "dates, statuses, and any identifiers. Output as plain structured text. "
                    "Be complete and literal."
                ),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_data,
                        },
                    },
                    {"type": "text", "text": "Extract all factual information from this image."},
                ],
            }
        ],
    )
    result = response.content[0].text
    _record_usage(_SONNET, response.usage)
    _save_cache(key, result)
    return result


def classify_intent(request_text: str) -> str:
    """Classify request_text as DELETION or NOT_APPLICABLE."""
    text_sha = _sha256_text(request_text)
    key = _cache_key("intent", text_sha)
    cached = _load_cache(key)
    if cached is not None:
        return cached

    client = _get_client()
    response = client.messages.create(
        model=_HAIKU,
        max_tokens=16,
        system=[
            {
                "type": "text",
                "text": (
                    "Classify whether the following request is asking to DELETE/ERASE personal data, "
                    "or is something else (access request, opt-out, correction, export, etc.). "
                    "Reply with exactly one word: DELETION or NOT_APPLICABLE."
                ),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": request_text}],
    )
    raw = response.content[0].text.strip().upper()
    result = "DELETION" if "DELETION" in raw else "NOT_APPLICABLE"
    _record_usage(_HAIKU, response.usage)
    _save_cache(key, result)
    return result
