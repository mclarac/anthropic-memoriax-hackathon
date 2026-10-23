import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import create_app

SAMPLE_RATE = 24000


class StubSynthesizer:
    sample_rate = SAMPLE_RATE
    voices = ["af_heart", "am_adam"]

    def __init__(self):
        self.calls: list[tuple[str, str, float]] = []

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        self.calls.append((text, voice, speed))
        t = np.arange(SAMPLE_RATE // 2) / SAMPLE_RATE
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class FailingSynthesizer(StubSynthesizer):
    def synthesize(self, text, voice, speed):
        raise RuntimeError("onnx exploded")


@pytest.fixture
def synth():
    return StubSynthesizer()


@pytest.fixture
def client(synth):
    with TestClient(create_app(synth)) as c:
        yield c


def test_health_reports_model_loaded(client):
    assert client.get("/health").json() == {"status": "ok", "model_loaded": True}


def test_voices_lists_synthesizer_voices(client):
    assert client.get("/voices").json() == ["af_heart", "am_adam"]


def test_tts_returns_16bit_mono_wav_at_native_rate(client):
    r = client.post("/tts", json={"text": "Hello there."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(r.content)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, SAMPLE_RATE)
        assert w.getnframes() == SAMPLE_RATE // 2


def test_tts_samples_are_scaled_to_int16(client):
    r = client.post("/tts", json={"text": "Hello"})
    with wave.open(io.BytesIO(r.content)) as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert 15000 < samples.max() <= 32767


def test_tts_clips_out_of_range_samples(synth):
    synth.synthesize = lambda text, voice, speed: np.array([2.0, -2.0], dtype=np.float32)
    with TestClient(create_app(synth)) as c:
        r = c.post("/tts", json={"text": "loud"})
    with wave.open(io.BytesIO(r.content)) as w:
        samples = np.frombuffer(w.readframes(2), dtype="<i2")
    assert list(samples) == [32767, -32767]


def test_tts_defaults_voice_and_speed(client, synth):
    client.post("/tts", json={"text": "Hi"})
    assert synth.calls == [("Hi", "af_heart", 1.0)]


def test_tts_passes_voice_and_speed(client, synth):
    client.post("/tts", json={"text": "Hi", "voice": "am_adam", "speed": 1.5})
    assert synth.calls == [("Hi", "am_adam", 1.5)]


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "x" * 601},
        {"text": "ok", "speed": 0.4},
        {"text": "ok", "speed": 2.1},
        {},
    ],
)
def test_tts_rejects_invalid_requests_with_422(client, synth, body):
    r = client.post("/tts", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]
    assert synth.calls == []


def test_tts_accepts_boundary_lengths(client):
    assert client.post("/tts", json={"text": "x"}).status_code == 200
    assert client.post("/tts", json={"text": "x" * 600}).status_code == 200


def test_tts_rejects_unknown_voice_with_422_naming_it(client, synth):
    r = client.post("/tts", json={"text": "Hi", "voice": "zz_nobody"})
    assert r.status_code == 422
    assert "zz_nobody" in r.json()["detail"]
    assert synth.calls == []


def test_tts_synthesis_failure_is_500_and_logged(synth, caplog):
    with TestClient(create_app(FailingSynthesizer()), raise_server_exceptions=False) as c:
        r = c.post("/tts", json={"text": "Hi"})
    assert r.status_code == 500
    assert r.json()["detail"] == "Speech synthesis failed"
    assert "onnx exploded" in caplog.text


def test_tts_empty_audio_is_500(synth):
    synth.synthesize = lambda text, voice, speed: np.zeros(0, dtype=np.float32)
    with TestClient(create_app(synth)) as c:
        assert c.post("/tts", json={"text": "..."}).status_code == 500
