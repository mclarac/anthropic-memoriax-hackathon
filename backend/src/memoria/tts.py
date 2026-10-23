"""Kokoro text-to-speech adapter: the real implementation of `ports.TTS`."""

from __future__ import annotations

import httpx


class TTSUnavailable(RuntimeError):
    """The Kokoro service could not produce audio (unreachable, timed out, or rejected the request)."""


class KokoroTTS:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 20,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        body = {"text": text} if voice is None else {"text": text, "voice": voice}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client:
                response = await client.post(f"{self._base_url}/tts", json=body)
        except httpx.TimeoutException as exc:
            raise TTSUnavailable(
                f"TTS service at {self._base_url} timed out after {self._timeout_s}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise TTSUnavailable(f"TTS service at {self._base_url} is unreachable: {exc}") from exc
        if response.is_error:
            raise TTSUnavailable(
                f"TTS service at {self._base_url} returned {response.status_code}: {_detail(response)}"
            )
        return response.content


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json()["detail"])
    except (ValueError, KeyError, TypeError):
        return response.text[:200]
