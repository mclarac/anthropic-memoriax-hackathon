"""Incremental sentence splitting for streamed speech.

The interviewer's text arrives in arbitrary deltas and each finished sentence
goes to TTS immediately. A boundary is only decided once the character after
it is known, so the output is identical however the text is chunked.
"""

from __future__ import annotations

_TERMINATORS = ".!?"
_CLOSERS = "\"')]}”’"
_OPENERS = "\"'([{“‘"
_ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "mr.", "mrs.", "ms.", "dr.", "vs.", "etc.", "u.s.", "prof.",
})


class SentenceSplitter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        """Add streamed text and return the sentences that are now complete."""
        self._buffer += delta
        sentences: list[str] = []
        while (end := self._find_boundary()) is not None:
            sentence = self._buffer[:end].strip()
            self._buffer = self._buffer[end:].lstrip()
            if sentence:
                sentences.append(sentence)
        return sentences

    def flush(self) -> str | None:
        """Return the unterminated remainder, if any, and reset."""
        remainder = self._buffer.strip()
        self._buffer = ""
        return remainder or None

    def _find_boundary(self) -> int | None:
        """Index just past the first confirmed sentence end, or None if undecided."""
        buf = self._buffer
        n = len(buf)
        i = 0
        while i < n:
            if buf[i] not in _TERMINATORS:
                i += 1
                continue
            run_end = i
            while run_end < n and buf[run_end] in _TERMINATORS:
                run_end += 1
            end = run_end
            while end < n and buf[end] in _CLOSERS:
                end += 1
            if end == n:
                return None
            if not buf[end].isspace():
                i = end
                continue
            run = buf[i:run_end]
            if run == "." and self._ends_with_abbreviation(buf[: i + 1]):
                i = end
                continue
            if run.startswith("..") and len(run) >= 3:
                after = end
                while after < n and buf[after].isspace():
                    after += 1
                if after == n:
                    return None
                if buf[after].islower():
                    i = after
                    continue
            return end
        return None

    @staticmethod
    def _ends_with_abbreviation(text: str) -> bool:
        token = text.rsplit(None, 1)[-1].lstrip(_OPENERS).lower()
        return token in _ABBREVIATIONS
