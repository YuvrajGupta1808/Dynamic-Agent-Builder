"""Fireworks-specific ChatOpenAI tweaks.

Fireworks serverless can stream ``reasoning_content`` on chat-completion deltas while
``content`` is empty for many tokens. langchain-openai intentionally omits
``reasoning_content`` from :func:`langchain_openai.chat_models.base._convert_delta_to_message_chunk`,
so reasoning never reaches LangGraph stream consumers. We patch generation chunks and
non-streaming results to mirror reasoning into ``AIMessageChunk`` / ``AIMessage``
``additional_kwargs`` so existing workbench normalizers emit ``thinking`` events.
"""

from __future__ import annotations

from typing import Any

import openai
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI


def _as_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=False)
    return {}


class FireworksReasoningChatOpenAI(ChatOpenAI):
    """ChatOpenAI that preserves Fireworks ``reasoning_content`` on assistant deltas."""

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        result = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if result is None:
            return None
        choices = chunk.get("choices") or []
        if not choices:
            return result
        delta = _as_plain_dict(choices[0].get("delta"))
        rc = delta.get("reasoning_content")
        if not rc:
            return result
        msg = result.message
        if not isinstance(msg, AIMessageChunk):
            return result
        extra = dict(msg.additional_kwargs)
        extra["reasoning_content"] = str(rc)
        new_msg = msg.model_copy(update={"additional_kwargs": extra})
        return ChatGenerationChunk(message=new_msg, generation_info=result.generation_info)

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        choices = response_dict.get("choices") or []
        new_generations: list[ChatGeneration] = []
        for i, gen in enumerate(result.generations):
            msg = gen.message
            if not isinstance(msg, AIMessage) or i >= len(choices):
                new_generations.append(gen)
                continue
            raw = _as_plain_dict(choices[i].get("message"))
            rc = raw.get("reasoning_content")
            if not rc:
                new_generations.append(gen)
                continue
            extra = dict(msg.additional_kwargs)
            extra["reasoning_content"] = str(rc)
            content: Any = msg.content
            if content in (None, ""):
                content = str(rc)
            new_msg = msg.model_copy(update={"content": content, "additional_kwargs": extra})
            new_generations.append(ChatGeneration(message=new_msg, generation_info=gen.generation_info))
        return ChatResult(generations=new_generations, llm_output=result.llm_output)
