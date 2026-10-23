"""Deterministic TTS for MEMORIA_MODE=fake and tests."""

from __future__ import annotations

import io
import wave

SAMPLE_RATE = 24000
DURATION_S = 0.2


def _silent_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"\x00\x00" * int(SAMPLE_RATE * DURATION_S))
    return buffer.getvalue()


class FakeTTS:
    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        return _silent_wav()
