import json

import httpx
import pytest

from memoria.tts import KokoroTTS, TTSUnavailable

WAV = b"RIFF....WAVEfmt "


def adapter(handler, **kwargs) -> KokoroTTS:
    return KokoroTTS("http://tts:8880", transport=httpx.MockTransport(handler), **kwargs)


async def test_synthesize_posts_text_and_returns_wav_bytes():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=WAV, headers={"content-type": "audio/wav"})

    audio = await adapter(handler).synthesize("Hello there.")

    assert audio == WAV
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "http://tts:8880/tts"
    assert json.loads(seen[0].content) == {"text": "Hello there."}


async def test_synthesize_sends_voice_when_given():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=WAV)

    await adapter(handler).synthesize("Hi", voice="am_adam")

    assert bodies == [{"text": "Hi", "voice": "am_adam"}]


async def test_trailing_slash_in_base_url_is_tolerated():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, content=WAV)

    tts = KokoroTTS("http://tts:8880/", transport=httpx.MockTransport(handler))
    await tts.synthesize("Hi")

    assert urls == ["http://tts:8880/tts"]


async def test_non_2xx_raises_with_status_and_service_detail():
    def handler(request):
        return httpx.Response(422, json={"detail": "Unknown voice 'nope'"})

    with pytest.raises(TTSUnavailable, match=r"422.*Unknown voice 'nope'"):
        await adapter(handler).synthesize("Hi", voice="nope")


async def test_server_error_raises():
    def handler(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(TTSUnavailable, match="500"):
        await adapter(handler).synthesize("Hi")


async def test_connection_error_names_the_service_url():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TTSUnavailable, match="http://tts:8880.*refused"):
        await adapter(handler).synthesize("Hi")


async def test_timeout_raises():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TTSUnavailable, match="timed out"):
        await adapter(handler, timeout_s=0.5).synthesize("Hi")
