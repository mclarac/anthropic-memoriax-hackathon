import io
import wave

from memoria.fakes.tts import FakeTTS


async def test_fake_tts_returns_valid_silent_wav():
    audio = await FakeTTS().synthesize("Hello there.")

    with wave.open(io.BytesIO(audio)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.getnframes() == 4800
        assert set(wav.readframes(wav.getnframes())) == {0}


async def test_fake_tts_ignores_voice_and_is_deterministic():
    tts = FakeTTS()
    assert await tts.synthesize("a", voice="am_adam") == await tts.synthesize("b")
