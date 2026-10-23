"""Deterministic in-process adapters for tests and MEMORIA_MODE=fake."""

from memoria.fakes.llm import FakeLLM
from memoria.fakes.memory import FakeAgentRuntime, FakeMemoryStore
from memoria.fakes.tts import FakeTTS

__all__ = ["FakeAgentRuntime", "FakeLLM", "FakeMemoryStore", "FakeTTS"]
