from memoria.renderers.blocks import Heading, ListBlock, Paragraph, parse_blocks
from memoria.renderers.citations import Citations
from memoria.renderers.inline import parse_inline

LEDGER = [
    {"id": "E4", "claim": "Setup takes two days.", "source": "Guide s2", "source_date": "2025-01-02"},
    {"id": "E9", "claim": "Costs fell 20%.", "source": "https://x.test", "source_date": None},
]


def texts(runs):
    return [(r.text, r.bold, r.italic, r.href, r.kind) for r in runs]


def test_plain_text_is_one_run():
    assert texts(parse_inline("hello world")) == [("hello world", False, False, None, "text")]


def test_bold_italic_and_nesting():
    runs = parse_inline("a **b *c* d** *e*")
    assert texts(runs) == [
        ("a ", False, False, None, "text"),
        ("b ", True, False, None, "text"),
        ("c", True, True, None, "text"),
        (" d", True, False, None, "text"),
        (" ", False, False, None, "text"),
        ("e", False, True, None, "text"),
    ]


def test_link_with_safe_scheme():
    runs = parse_inline("see [docs](https://example.com/a?b=1) now")
    assert ("docs", False, False, "https://example.com/a?b=1", "text") in texts(runs)


def test_link_with_unsafe_scheme_is_plain_text():
    runs = parse_inline("[x](javascript:alert(1))")
    assert all(r.href is None for r in runs)
    assert "".join(r.text for r in runs).startswith("[x](javascript:alert(1")


def test_markers_and_placeholder_kinds():
    runs = parse_inline("Fast.[E4][E9] [PLACEHOLDER: add ROI] done")
    kinds = [(r.kind, r.text) for r in runs]
    assert kinds == [
        ("text", "Fast."),
        ("marker", "E4"),
        ("marker", "E9"),
        ("text", " "),
        ("placeholder", "[PLACEHOLDER: add ROI]"),
        ("text", " done"),
    ]


def test_unclosed_emphasis_stays_literal():
    assert "".join(r.text for r in parse_inline("2 * 3 and **open")) == "2 * 3 and **open"


def test_blocks_headings_paragraphs_lists():
    md = "# One\n\npara line\ncontinued\n\n## Two\n- a\n- b\n\n1. x\n2) y\n\n### Three\n#### Four"
    blocks = parse_blocks(md)
    kinds = [Heading, Paragraph, Heading, ListBlock, ListBlock, Heading, Paragraph]
    assert [type(b) for b in blocks] == kinds
    assert [b.level for b in blocks if isinstance(b, Heading)] == [1, 2, 3]
    assert "".join(r.text for r in blocks[1].runs) == "para line continued"
    assert [b.ordered for b in blocks if isinstance(b, ListBlock)] == [False, True]
    assert len(blocks[4].items) == 2
    assert "".join(r.text for r in blocks[6].runs) == "#### Four"


def test_heading_shift():
    blocks = parse_blocks("# One\n### Three", shift=1)
    assert [b.level for b in blocks] == [2, 4]


def test_star_bullet_is_a_list_not_italics():
    blocks = parse_blocks("* one\n* two")
    assert isinstance(blocks[0], ListBlock) and len(blocks[0].items) == 2


def test_citations_number_in_order_of_first_use_and_flag_missing():
    cites = Citations(LEDGER)
    runs = cites.resolve(parse_inline("A[E9] B[E4] C[E9] D[E99]"))
    shown = [(r.kind, r.text) for r in runs if r.kind != "text"]
    assert shown == [("cite", "1"), ("cite", "2"), ("cite", "1"), ("missing", "[E99: missing evidence]")]
    assert [(n, e["id"]) for n, e in cites.references()] == [(1, "E9"), (2, "E4")]


def test_reference_text_includes_claim_source_and_date():
    cites = Citations(LEDGER)
    cites.resolve(parse_inline("x[E4] y[E9]"))
    lines = [cites.reference_text(e) for _, e in cites.references()]
    assert lines[0] == "Setup takes two days. Source: Guide s2 (2025-01-02)"
    assert lines[1] == "Costs fell 20%. Source: https://x.test (undated)"


def test_drop_known_removes_found_markers_only():
    cites = Citations(LEDGER)
    runs = cites.drop_known(parse_inline("A.[E4] B.[E99]"))
    assert "".join(r.text for r in runs) == "A. B.[E99: missing evidence]"
