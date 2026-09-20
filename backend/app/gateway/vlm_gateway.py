"""VLM (vision-capable model) Gateway — the fallback-only path for
scanned/image documents (design §8.2 Profiler: "Model tier: mid/strong with
vision fallback"; §22.1: "if empty or image -> VLM page reads"; §30: "VLM
fallback -> still empty -> ask user to paste text").

Same shape as `llm_gateway.py`/`embedding_gateway.py`: a provider-agnostic
interface that degrades deterministically (`degraded=True`, never an
exception) when no provider is configured — the project default. Unlike text
extraction and embeddings, there is no meaningful *deterministic* fallback
for "read text from a photo of a page" (no OCR dependency is in scope for
this phase), so the degraded path here always reports failure rather than
guessing — matching design §30's documented failure mode exactly: "ask user
for text paste; continue with intake-only claims," not a fabricated read.
"""
from __future__ import annotations

import base64
from abc import ABC, abstractmethod

import httpx

from pydantic import BaseModel

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)



class VLMPageReadRequest(BaseModel):
    document_id: str
    image_bytes_b64: str
    page_index: int = 0


class VLMPageReadResponse(BaseModel):
    text: str = ""
    degraded: bool = False


class VLMGateway(ABC):
    @abstractmethod
    async def read_page(self, request: VLMPageReadRequest) -> VLMPageReadResponse: ...


class DegradedVLMGateway(VLMGateway):
    """Default gateway when no vision-capable provider is configured
    (`settings.llm_provider == "none"`). Always reports `degraded=True` with
    empty text — there is no offline stand-in for OCR/vision reading, so the
    caller (document_parser -> ProfilerAgent) must fall through to design
    §30's "ask user to paste text" path rather than treat this as a silent
    zero-claims success.
    """

    async def read_page(self, request: VLMPageReadRequest) -> VLMPageReadResponse:
        return VLMPageReadResponse(text="", degraded=True)


_TRANSCRIBE_PROMPT = (
    "Transcribe ALL the text visible in this page image exactly as written, preserving line breaks. "
    "Output the plain text only: no commentary, no markdown fences, and do not add anything that is not on the page. "
    "If the image contains no readable text, output an empty string."
)


def _image_mime(image: bytes) -> str:
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"\x89PNG"):
        return "image/png"
    return "image/png"


class HuggingFaceVLMGateway(VLMGateway):
    """Vision fallback through the Hugging Face router's OpenAI-compatible chat API
    (`VLM_PROVIDER=huggingface`, needs `HF_TOKEN`). The page image is sent as a base64 data URL;
    the model is asked to transcribe, never to interpret. Whatever it returns is only ever *text
    to be verified*: the Profiler's verbatim-span check still runs against it, so a hallucinated
    line cannot become evidence unless it is also in the transcript the claim quotes."""

    def __init__(self, *, api_key: str, model: str, base_url: str, timeout_s: float = 60.0, client: httpx.AsyncClient | None = None) -> None:
        self._api_key, self._model, self._url = api_key, model, f"{base_url.rstrip('/')}/chat/completions"
        self._timeout_s, self._client = timeout_s, client

    async def read_page(self, request: VLMPageReadRequest) -> VLMPageReadResponse:
        try:
            image = base64.b64decode(request.image_bytes_b64, validate=True)
        except Exception:  # noqa: BLE001
            return VLMPageReadResponse(text="", degraded=True)
        body = {
            "model": self._model,
            "max_tokens": 2048,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _TRANSCRIBE_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{_image_mime(image)};base64,{request.image_bytes_b64}"}},
                    ],
                }
            ],
        }
        try:
            http = self._client or httpx.AsyncClient(timeout=self._timeout_s)
            try:
                resp = await http.post(self._url, json=body, headers={"Authorization": f"Bearer {self._api_key}"})
            finally:
                if self._client is None:
                    await http.aclose()
            if resp.status_code != 200:
                logger.warning("edupath.vlm.rejected", status=resp.status_code)
                return VLMPageReadResponse(text="", degraded=True)
            text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError, AttributeError):
            logger.warning("edupath.vlm.failed", exc_info=True)
            return VLMPageReadResponse(text="", degraded=True)
        return VLMPageReadResponse(text=text, degraded=not text)


def get_vlm_gateway() -> VLMGateway:
    """`VLM_PROVIDER=huggingface` (and an `HF_TOKEN`) -> a real vision read; anything else -> the degraded
    gateway ("we could not read it: paste the text", design section 30)."""
    settings = get_settings()
    if settings.vlm_provider == "huggingface" and settings.hf_token:
        return HuggingFaceVLMGateway(api_key=settings.hf_token, model=settings.vlm_model, base_url=settings.vlm_base_url)
    return DegradedVLMGateway()
