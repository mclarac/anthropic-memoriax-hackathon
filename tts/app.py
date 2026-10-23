"""Kokoro-82M text-to-speech service: POST /tts returns 16-bit mono WAV."""

import io
import logging
import os
import wave
from contextlib import asynccontextmanager
from typing import Protocol

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

logger = logging.getLogger("tts")

DEFAULT_VOICE = "af_heart"
MAX_TEXT_CHARS = 600


class Synthesizer(Protocol):
    sample_rate: int
    voices: list[str]

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        """Return mono float32 samples in [-1, 1] at `sample_rate`."""
        ...


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    voice: str = DEFAULT_VOICE
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def encode_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def load_kokoro() -> Synthesizer:
    from synthesizer import KokoroSynthesizer

    return KokoroSynthesizer(
        os.environ.get("KOKORO_MODEL_PATH", "/models/kokoro-v1.0.onnx"),
        os.environ.get("KOKORO_VOICES_PATH", "/models/voices-v1.0.bin"),
    )


def create_app(synthesizer: Synthesizer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.synthesizer = synthesizer or load_kokoro()
        yield

    app = FastAPI(title="memoria-tts", lifespan=lifespan)
    app.state.synthesizer = None

    @app.exception_handler(RequestValidationError)
    async def validation_message(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in exc.errors()
        )
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model_loaded": app.state.synthesizer is not None}

    @app.get("/voices")
    def voices() -> list[str]:
        return list(app.state.synthesizer.voices)

    # A sync handler runs in the threadpool, keeping the event loop free during CPU-bound inference.
    @app.post("/tts")
    def tts(request: TTSRequest) -> Response:
        engine: Synthesizer = app.state.synthesizer
        if request.voice not in engine.voices:
            raise HTTPException(422, f"Unknown voice '{request.voice}'")
        try:
            samples = engine.synthesize(request.text, request.voice, request.speed)
            if samples.size == 0:
                raise ValueError("synthesizer returned no audio")
        except Exception:
            logger.exception("Synthesis failed for voice=%s speed=%s", request.voice, request.speed)
            raise HTTPException(500, "Speech synthesis failed") from None
        return Response(encode_wav(samples, engine.sample_rate), media_type="audio/wav")

    return app
