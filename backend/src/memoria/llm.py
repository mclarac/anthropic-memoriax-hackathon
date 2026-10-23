"""Anthropic Messages API adapter for the LLM port."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import anthropic

from memoria.chain_prompts import MODEL
from memoria.ports import LLMRequest, LLMResult, Usage

MAX_PAUSE_CONTINUATIONS = 5


class LLMOutputError(Exception):
    """The model's output could not be used for the stage that asked for it."""

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"stage {stage}: {detail}")
        self.stage = stage


def _server_tool(name: str, max_uses: int) -> dict[str, Any]:
    versions = {"web_search": "web_search_20250305", "web_fetch": "web_fetch_20250910"}
    if name not in versions:
        raise ValueError(f"unsupported server tool: {name}")
    tool: dict[str, Any] = {"type": versions[name], "name": name}
    if max_uses > 0:
        tool["max_uses"] = max_uses
    return tool


def _system_blocks(req: LLMRequest) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": req.system}]
    if req.tenant_block:
        blocks.append({"type": "text", "text": req.tenant_block})
    # One breakpoint on the last block caches the whole stable prefix.
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _user_message(req: LLMRequest) -> dict[str, Any]:
    return {"role": "user", "content": [*req.documents, {"type": "text", "text": req.user}]}


def _output_config(req: LLMRequest, *, with_schema: bool) -> dict[str, Any] | None:
    config: dict[str, Any] = {}
    if req.effort:
        config["effort"] = req.effort
    if with_schema and req.schema:
        config["format"] = {"type": "json_schema", "schema": req.schema}
    return config or None


def _add_usage(total: Usage, usage: Any) -> None:
    total.input_tokens += usage.input_tokens or 0
    total.output_tokens += usage.output_tokens or 0
    total.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", None) or 0
    total.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", None) or 0


class AnthropicLLM:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str = MODEL) -> None:
        self._client = client
        self._model = model

    def _kwargs(
        self, req: LLMRequest, messages: list[dict[str, Any]], *, with_schema: bool
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": req.max_tokens,
            "system": _system_blocks(req),
            "messages": messages,
        }
        if (output_config := _output_config(req, with_schema=with_schema)) is not None:
            kwargs["output_config"] = output_config
        if req.tools:
            kwargs["tools"] = [_server_tool(name, req.max_tool_calls) for name in req.tools]
        return kwargs

    async def complete(self, req: LLMRequest) -> LLMResult:
        usage = Usage()
        messages = [_user_message(req)]
        use_loop = bool(req.tools)
        # Structured output must not run during the tool loop; it is applied on the
        # finalize call, or on the only call when there are no tools.
        schema_on_loop_calls = not use_loop

        first = self._kwargs(req, messages, with_schema=schema_on_loop_calls)
        response = await self._client.messages.create(**first)
        _add_usage(usage, response.usage)

        continuations = 0
        while response.stop_reason == "pause_turn":
            if continuations == MAX_PAUSE_CONTINUATIONS:
                raise LLMOutputError(req.stage, f"still paused after {MAX_PAUSE_CONTINUATIONS} continuations")
            continuations += 1
            messages.append(self._assistant_turn(response))
            response = await self._client.messages.create(**self._kwargs(req, messages, with_schema=False))
            _add_usage(usage, response.usage)

        if use_loop and req.finalize_user:
            messages.append(self._assistant_turn(response))
            messages.append({"role": "user", "content": [{"type": "text", "text": req.finalize_user}]})
            kwargs = self._kwargs(req, messages, with_schema=True)
            kwargs["tool_choice"] = {"type": "none"}
            response = await self._client.messages.create(**kwargs)
            _add_usage(usage, response.usage)

        texts = [block.text for block in response.content if block.type == "text"]
        data = self._parse_object(req.stage, texts[-1] if texts else "") if req.schema else None
        return LLMResult(text="".join(texts), data=data, usage=usage, stop_reason=response.stop_reason)

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        kwargs = self._kwargs(replace(req, tools=[]), [_user_message(req)], with_schema=False)
        async with self._client.messages.stream(**kwargs) as stream:
            async for delta in stream.text_stream:
                yield delta

    @staticmethod
    def _assistant_turn(response: Any) -> dict[str, Any]:
        content = [block.model_dump(exclude_none=True) for block in response.content]
        return {"role": "assistant", "content": content}

    @staticmethod
    def _parse_object(stage: str, raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(stage, f"output is not valid JSON ({exc.msg})") from exc
        if not isinstance(parsed, dict):
            raise LLMOutputError(stage, f"output is JSON {type(parsed).__name__}, expected an object")
        return parsed
