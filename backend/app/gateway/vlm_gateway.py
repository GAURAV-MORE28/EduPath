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

from abc import ABC, abstractmethod

from pydantic import BaseModel



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


def get_vlm_gateway():
    """Always the deterministic/degraded gateway: no vision provider is
    implemented in this project, so a configured `LLM_PROVIDER` (which only
    routes the LLM Gateway) must not make this raise -- Phase 12 fixed a crash
    where any provider other than "none" turned intake/upload/planning into a
    500. The degrade is reported honestly by each response's own flags."""
    return DegradedVLMGateway()
