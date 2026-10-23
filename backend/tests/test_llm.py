import copy
import json

import pytest
from anthropic.types import Message, ServerToolUseBlock, TextBlock, Usage

from memoria.chain_prompts import MODEL
from memoria.llm import AnthropicLLM, LLMOutputError
from memoria.ports import LLMRequest


def message(*blocks, stop_reason="end_turn", input_tokens=10, output_tokens=5, cache_read=0, cache_write=0):
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model=MODEL,
        content=list(blocks),
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


def text(value: str) -> TextBlock:
    return TextBlock(type="text", text=value, citations=None)


def search_call() -> ServerToolUseBlock:
    return ServerToolUseBlock(type="server_tool_use", id="srv_1", name="web_search", input={"query": "q"})


class FakeStream:
    def __init__(self, deltas):
        self._deltas = deltas

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for delta in self._deltas:
                yield delta

        return gen()


class FakeMessages:
    def __init__(self, responses, stream_deltas=()):
        self._responses = list(responses)
        self._stream_deltas = list(stream_deltas)
        self.calls: list[dict] = []
        self.stream_calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self._responses.pop(0)

    def stream(self, **kwargs):
        self.stream_calls.append(copy.deepcopy(kwargs))
        return FakeStream(self._stream_deltas)


class FakeClient:
    def __init__(self, responses=(), stream_deltas=()):
        self.messages = FakeMessages(responses, stream_deltas)


def request(**overrides) -> LLMRequest:
    base = {"stage": "deal_brief", "system": "SYS", "user": "USER", "max_tokens": 321}
    base.update(overrides)
    return LLMRequest(**base)


SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}


async def test_plain_request_shape_and_text_result():
    client = FakeClient([message(text("hello"), stop_reason="end_turn")])
    result = await AnthropicLLM(client).complete(request())

    (call,) = client.messages.calls
    assert call["model"] == MODEL
    assert call["max_tokens"] == 321
    assert call["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert call["messages"] == [{"role": "user", "content": [{"type": "text", "text": "USER"}]}]
    assert "output_config" not in call
    assert "tools" not in call
    assert "tool_choice" not in call
    assert result.text == "hello"
    assert result.data is None
    assert result.stop_reason == "end_turn"


async def test_custom_model_is_used():
    client = FakeClient([message(text("x"))])
    await AnthropicLLM(client, model="other-model").complete(request())
    assert client.messages.calls[0]["model"] == "other-model"


async def test_tenant_block_is_second_system_block_and_carries_cache_control():
    client = FakeClient([message(text("x"))])
    await AnthropicLLM(client).complete(request(tenant_block="TENANT"))

    assert client.messages.calls[0]["system"] == [
        {"type": "text", "text": "SYS"},
        {"type": "text", "text": "TENANT", "cache_control": {"type": "ephemeral"}},
    ]


async def test_documents_come_before_the_user_text_block():
    docs = [{"type": "document", "source": {"type": "file", "file_id": "f1"}, "title": "A"}]
    client = FakeClient([message(text("x"))])
    await AnthropicLLM(client).complete(request(documents=docs))

    content = client.messages.calls[0]["messages"][0]["content"]
    assert content == [*docs, {"type": "text", "text": "USER"}]


async def test_schema_sets_json_output_format_and_parses_last_text_block():
    client = FakeClient([message(text("thinking aloud"), text('{"a": 1}'))])
    result = await AnthropicLLM(client).complete(request(schema=SCHEMA))

    assert client.messages.calls[0]["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    assert result.data == {"a": 1}


async def test_effort_goes_into_output_config_with_and_without_schema():
    client = FakeClient([message(text("x")), message(text('{"a": 2}'))])
    llm = AnthropicLLM(client)
    await llm.complete(request(effort="high"))
    await llm.complete(request(effort="low", schema=SCHEMA))

    assert client.messages.calls[0]["output_config"] == {"effort": "high"}
    assert client.messages.calls[1]["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": SCHEMA},
    }


@pytest.mark.parametrize("payload", ["not json", "[1, 2]", '"str"', ""])
async def test_non_object_json_raises_with_stage_name(payload):
    client = FakeClient([message(text(payload))])
    with pytest.raises(LLMOutputError) as err:
        await AnthropicLLM(client).complete(request(stage="personas", schema=SCHEMA))
    assert "personas" in str(err.value)
    assert err.value.stage == "personas"


async def test_schema_without_any_text_block_raises():
    client = FakeClient([message(search_call())])
    with pytest.raises(LLMOutputError):
        await AnthropicLLM(client).complete(request(schema=SCHEMA))


async def test_usage_fields_are_carried_through():
    client = FakeClient([message(text("x"), input_tokens=7, output_tokens=3, cache_read=100, cache_write=40)])
    result = await AnthropicLLM(client).complete(request())

    assert (result.usage.input_tokens, result.usage.output_tokens) == (7, 3)
    assert (result.usage.cache_read_input_tokens, result.usage.cache_creation_input_tokens) == (100, 40)


RESEARCH = {
    "stage": "research",
    "tools": ["web_search", "web_fetch"],
    "max_tool_calls": 20,
    "finalize_user": "FINALIZE",
    "schema": SCHEMA,
    "effort": "medium",
}


async def test_research_declares_server_tools_and_defers_schema_to_finalize_call():
    client = FakeClient([
        message(search_call(), text("findings"), input_tokens=100, output_tokens=50),
        message(text('{"a": 9}'), input_tokens=200, output_tokens=20),
    ])
    result = await AnthropicLLM(client).complete(request(**RESEARCH))

    loop_call, final_call = client.messages.calls
    tools = [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 20},
        {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 20},
    ]
    assert loop_call["tools"] == tools
    assert "tool_choice" not in loop_call
    assert loop_call["output_config"] == {"effort": "medium"}

    assert final_call["tools"] == tools
    assert final_call["tool_choice"] == {"type": "none"}
    assert final_call["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": SCHEMA},
    }
    assert final_call["messages"][1]["role"] == "assistant"
    assert final_call["messages"][1]["content"][0]["type"] == "server_tool_use"
    assert final_call["messages"][2] == {"role": "user", "content": [{"type": "text", "text": "FINALIZE"}]}

    assert result.data == {"a": 9}
    assert result.usage.input_tokens == 300
    assert result.usage.output_tokens == 70


async def test_pause_turn_appends_assistant_content_and_continues():
    client = FakeClient([
        message(search_call(), stop_reason="pause_turn"),
        message(text("done"), stop_reason="end_turn"),
    ])
    result = await AnthropicLLM(client).complete(
        request(stage="research", tools=["web_search"], max_tool_calls=3)
    )

    first, second = client.messages.calls
    assert len(first["messages"]) == 1
    assert [m["role"] for m in second["messages"]] == ["user", "assistant"]
    assert second["messages"][1]["content"][0]["id"] == "srv_1"
    assert "tool_choice" not in second
    assert result.text == "done"
    assert result.usage.input_tokens == 20


async def test_pause_turn_loop_is_capped_at_five_continuations():
    client = FakeClient([message(search_call(), stop_reason="pause_turn") for _ in range(6)])
    with pytest.raises(LLMOutputError) as err:
        await AnthropicLLM(client).complete(request(stage="research", tools=["web_search"], max_tool_calls=3))

    assert "research" in str(err.value)
    assert len(client.messages.calls) == 6


async def test_five_continuations_then_end_turn_succeeds():
    responses = [message(search_call(), stop_reason="pause_turn") for _ in range(5)] + [message(text("ok"))]
    client = FakeClient(responses)
    research = request(stage="research", tools=["web_search"], max_tool_calls=3)
    result = await AnthropicLLM(client).complete(research)
    assert result.text == "ok"


async def test_tools_without_finalize_user_make_a_single_loop_with_no_tool_choice():
    client = FakeClient([message(text("answer"))])
    await AnthropicLLM(client).complete(request(tools=["web_search"], max_tool_calls=2))

    assert len(client.messages.calls) == 1
    assert "tool_choice" not in client.messages.calls[0]


async def test_unknown_tool_name_is_rejected():
    client = FakeClient([])
    with pytest.raises(ValueError, match="code_interpreter"):
        await AnthropicLLM(client).complete(request(tools=["code_interpreter"], max_tool_calls=1))


async def test_stream_yields_text_deltas_with_system_blocks_and_no_schema_or_tools():
    client = FakeClient(stream_deltas=["Hel", "lo ", "there."])
    llm = AnthropicLLM(client)
    deltas = [d async for d in llm.stream(request(stage="interviewer", tenant_block="TENANT", effort="low"))]

    assert deltas == ["Hel", "lo ", "there."]
    (call,) = client.messages.stream_calls
    assert call["model"] == MODEL
    assert call["max_tokens"] == 321
    assert call["system"] == [
        {"type": "text", "text": "SYS"},
        {"type": "text", "text": "TENANT", "cache_control": {"type": "ephemeral"}},
    ]
    assert call["messages"] == [{"role": "user", "content": [{"type": "text", "text": "USER"}]}]
    assert call["output_config"] == {"effort": "low"}
    assert "tools" not in call
    assert json.dumps(call)
