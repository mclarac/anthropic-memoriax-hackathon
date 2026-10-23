"""Kokoro ONNX synthesizer, kept apart from the HTTP layer so the app can be tested with a stub."""

import numpy as np
from kokoro_onnx import Kokoro
from kokoro_onnx.config import SAMPLE_RATE


class KokoroSynthesizer:
    sample_rate = SAMPLE_RATE

    def __init__(self, model_path: str, voices_path: str) -> None:
        self._kokoro = Kokoro(model_path, voices_path)
        self.voices: list[str] = self._kokoro.get_voices()

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        audio, _ = self._kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        return audio
