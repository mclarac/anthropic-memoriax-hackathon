import pytest

from memoria.text import SentenceSplitter


def run(chunks: list[str]) -> list[str]:
    splitter = SentenceSplitter()
    out: list[str] = []
    for chunk in chunks:
        out.extend(splitter.feed(chunk))
    tail = splitter.flush()
    if tail:
        out.append(tail)
    return out


def by_char(text: str) -> list[str]:
    return run(list(text))


CASES = [
    ("Hello there. How are you? Great!", ["Hello there.", "How are you?", "Great!"]),
    ("The price is 3.5 million. Is that right?", ["The price is 3.5 million.", "Is that right?"]),
    ("Ask Dr. Patel about it. Then call Mr. Lee.", ["Ask Dr. Patel about it.", "Then call Mr. Lee."]),
    (
        "We sell to utilities, banks, etc. and others. Fine.",
        ["We sell to utilities, banks, etc. and others.", "Fine."],
    ),
    ("Use a tool, i.e. a monitor, e.g. ours. Okay.", ["Use a tool, i.e. a monitor, e.g. ours.", "Okay."]),
    ("Acme vs. Beta is close. Who wins?", ["Acme vs. Beta is close.", "Who wins?"]),
    ("Mrs. Gomez works in the U.S. office. Right?", ["Mrs. Gomez works in the U.S. office.", "Right?"]),
    ("Well... maybe so. Next one.", ["Well... maybe so.", "Next one."]),
    ("Wait... Really? Yes.", ["Wait...", "Really?", "Yes."]),
    ('He said "stop." Then left.', ['He said "stop."', "Then left."]),
    ("(See above.) Then continue.", ["(See above.)", "Then continue."]),
    ("What?! No way.", ["What?!", "No way."]),
    ("No terminator at all", ["No terminator at all"]),
    ("  Padded.   Spaced.  ", ["Padded.", "Spaced."]),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_whole_text_in_one_chunk(text, expected):
    assert run([text]) == expected


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_one_character_at_a_time_matches(text, expected):
    assert by_char(text) == expected


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_awkward_chunk_boundaries_match(text, expected):
    for size in (2, 3, 5, 7):
        chunks = [text[i : i + size] for i in range(0, len(text), size)]
        assert run(chunks) == expected


def test_sentence_is_held_until_the_next_character_confirms_the_boundary():
    splitter = SentenceSplitter()
    assert splitter.feed("Cost is 3.") == []
    assert splitter.feed("5 dollars. ") == ["Cost is 3.5 dollars."]


def test_flush_returns_none_when_nothing_remains():
    splitter = SentenceSplitter()
    assert splitter.feed("Done. ") == ["Done."]
    assert splitter.flush() is None
    assert splitter.feed("Tail") == []
    assert splitter.flush() == "Tail"
    assert splitter.flush() is None


def test_flush_on_empty_splitter_is_none():
    assert SentenceSplitter().flush() is None


def test_splitter_is_reusable_after_flush():
    splitter = SentenceSplitter()
    splitter.feed("One.")
    splitter.flush()
    assert splitter.feed("Two. ") == ["Two."]
    assert splitter.flush() is None
