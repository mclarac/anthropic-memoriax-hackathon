from email.parser import BytesParser
from email.policy import default

from memoria.renderers import render_asset

LEDGER = [{"id": "E4", "claim": "c", "source": "s", "source_date": None}]
EMAILS = {
    "emails": [
        {
            "step": 1, "send_day": 0, "persona_id": "P1", "subject": "Cutting onboarding time",
            "preview_text": "Two days, not two weeks",
            "body_text": "Hi,\nWe cut setup to two days.[E4]\n\nBest", "ask": "15 minutes?",
        },
        {
            "step": 2, "send_day": 3, "persona_id": "P2", "subject": "Café <costs> & more",
            "preview_text": "p", "body_text": "Figures[E99] - see [PLACEHOLDER: link]", "ask": "Reply?",
        },
    ],
    "placeholders": [],
}


def parse(path):
    return BytesParser(policy=default).parsebytes(path.read_bytes())


def test_one_eml_per_email_plus_markdown(tmp_path):
    files = render_asset("email_sequence", EMAILS, LEDGER, tmp_path, "seq", "/f")
    assert [f.url for f in files] == ["/f/seq.md", "/f/seq-step1.eml", "/f/seq-step2.eml"]
    assert [f.format for f in files] == ["md", "eml", "eml"]


def test_eml_parses_with_headers_and_plain_body(tmp_path):
    render_asset("email_sequence", EMAILS, LEDGER, tmp_path, "seq", "/f")
    msg = parse(tmp_path / "seq-step1.eml")
    assert msg["Subject"] == "Cutting onboarding time"
    assert "@example.invalid" in msg["To"]
    assert "@example.invalid" in msg["From"]
    assert not msg.is_multipart()
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content().replace("\r\n", "\n").strip() == "Hi,\nWe cut setup to two days.[E4]\n\nBest"
    assert msg["X-Send-Day"] == "0"
    assert msg["X-Preview-Text"] == "Two days, not two weeks"


def test_eml_preserves_unicode_and_flags_missing_evidence(tmp_path):
    render_asset("email_sequence", EMAILS, LEDGER, tmp_path, "seq", "/f")
    msg = parse(tmp_path / "seq-step2.eml")
    assert msg["Subject"] == "Café <costs> & more"
    assert "[E99: missing evidence]" in msg.get_content()
    assert "[PLACEHOLDER: link]" in msg.get_content()


def test_markdown_lists_every_email(tmp_path):
    render_asset("email_sequence", EMAILS, LEDGER, tmp_path, "seq", "/f")
    md = (tmp_path / "seq.md").read_text()
    for needle in (
        "Email 1", "Email 2", "Cutting onboarding time", "Two days, not two weeks",
        "Day 3", "15 minutes?", "[E99: missing evidence]",
    ):
        assert needle in md
