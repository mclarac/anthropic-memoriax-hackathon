"""Application wiring: choose adapters, build the orchestrator, create the FastAPI app."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from memoria import api
from memoria.chain import BuildRunner
from memoria.config import Settings
from memoria.interview import InterviewEngine
from memoria.ports import LLM, TTS, AgentRuntime, MemoryStore
from memoria.storage import Storage


@dataclass
class Ports:
    llm: LLM
    agents: AgentRuntime
    memory: MemoryStore
    tts: TTS


def build_ports(settings: Settings) -> Ports:
    # Adapters are imported here so fake mode never loads the Anthropic SDK.
    if settings.mode == "fake":
        from memoria.fakes import FakeAgentRuntime, FakeLLM, FakeMemoryStore, FakeTTS

        memory = FakeMemoryStore()
        return Ports(llm=FakeLLM(), agents=FakeAgentRuntime(memory), memory=memory, tts=FakeTTS())

    if settings.anthropic_api_key is None:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required when MEMORIA_MODE=live; set it or use MEMORIA_MODE=fake"
        )

    import anthropic

    from memoria.llm import AnthropicLLM
    from memoria.memory.agents import ManagedAgentRuntime
    from memoria.memory.store import ManagedMemoryStore
    from memoria.tts import KokoroTTS

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    registry_path = settings.data_dir / "registry.json"
    return Ports(
        llm=AnthropicLLM(client, settings.model),
        agents=ManagedAgentRuntime(client, registry_path, settings.model),
        memory=ManagedMemoryStore(client, registry_path),
        tts=KokoroTTS(settings.tts_url),
    )


def create_app(settings: Settings | None = None, ports: Ports | None = None) -> FastAPI:
    settings = settings or Settings()
    ports = ports or build_ports(settings)
    storage = Storage(settings.data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        for task in list(app.state.build_tasks):
            task.cancel()
        await asyncio.gather(*app.state.build_tasks, return_exceptions=True)

    app = FastAPI(title="Memoria", lifespan=lifespan)
    app.state.settings = settings
    app.state.ports = ports
    app.state.storage = storage
    app.state.engine = InterviewEngine(ports.llm, date.today)
    app.state.runner = BuildRunner(ports, storage, date.today)
    app.state.build_tasks = set()
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(api.router)
    return app
