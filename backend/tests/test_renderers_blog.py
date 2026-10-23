from html.parser import HTMLParser

from memoria.renderers import render_asset

LEDGER = [
    {"id": "E4", "claim": "Setup takes two days.", "source": "Guide s2", "source_date": "2025-01-02"},
    {
        "id": "E9", "claim": "Costs fell <20%> & more.", "source": "https://x.test/a?b=1&c=2",
        "source_date": None,
    },
]

BLOG = {
    "title": "Fast <script>alert(1)</script> setup",
    "slug": "fast-setup",
    "meta_description": 'Setup in "two" days & no fuss',
    "body_markdown": (
        "# Intro\n\nWe ship **fast**.[E4][E9] See [docs](https://example.com) <b>raw</b> & more.\n\n"
        "- one [PLACEHOLDER: customer name]\n- two [E99]\n\n1. first\n2. second"
    ),
    "cta": "Book a demo",
    "placeholders": ["[PLACEHOLDER: customer name]"],
}


class Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.append((tag, dict(attrs)))


def render(tmp_path):
    files = render_asset("blog", BLOG, LEDGER, tmp_path / "out", "post", "/api/files/s1")
    return {f.format: f for f in files}, tmp_path / "out"


def test_blog_produces_md_and_html_with_urls(tmp_path):
    files, out = render(tmp_path)
    assert set(files) == {"md", "html"}
    assert files["html"].url == "/api/files/s1/post.html"
    assert files["md"].url == "/api/files/s1/post.md"
    assert files["html"].size_bytes == (out / "post.html").stat().st_size > 0


def test_html_is_standalone_semantic_and_escaped(tmp_path):
    _, out = render(tmp_path)
    html = (out / "post.html").read_text()
    assert html.startswith("<!doctype html>")
    assert "<script>" not in html
    assert "Fast &lt;script&gt;alert(1)&lt;/script&gt; setup" in html
    assert "&lt;b&gt;raw&lt;/b&gt; &amp; more" in html
    collected = Collect()
    collected.feed(html)
    assert {"article", "h1", "h2", "ul", "ol", "li", "title", "style", "sup"} <= set(collected.tags)
    meta = [a for t, a in collected.attrs if t == "meta" and a.get("name") == "description"]
    assert meta[0]["content"] == 'Setup in "two" days & no fuss'
    assert "src=" not in html and "<link" not in html


def test_html_references_and_flags(tmp_path):
    _, out = render(tmp_path)
    html = (out / "post.html").read_text()
    assert html.index("References") < html.index("Setup takes two days.")
    assert "Setup takes two days. Source: Guide s2 (2025-01-02)" in html
    assert "Costs fell &lt;20%&gt; &amp; more. Source: https://x.test/a?b=1&amp;c=2 (undated)" in html
    assert '<a href="#ref-1">' in html and '<a href="#ref-2">' in html
    assert '<mark class="placeholder">[PLACEHOLDER: customer name]</mark>' in html
    assert "[E99: missing evidence]" in html
    assert '<a href="https://example.com">docs</a>' in html
    assert "Book a demo" in html


def test_markdown_keeps_markers_appends_references_and_flags_missing(tmp_path):
    _, out = render(tmp_path)
    md = (out / "post.md").read_text()
    assert md.startswith("# Fast <script>alert(1)</script> setup")
    assert "[E4][E9]" in md
    assert "[E99: missing evidence]" in md
    assert "## References" in md
    assert "- [E4] Setup takes two days. Source: Guide s2 (2025-01-02)" in md
    assert "Book a demo" in md
