"""Email sequence output: one markdown overview and one RFC 5322 file per email."""

from __future__ import annotations

from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

from memoria.renderers.citations import Citations
from memoria.renderers.markdown_text import cited_ids, flag_missing_markers, references_markdown

# .invalid is reserved by RFC 2606, so these can never be delivered to a real mailbox.
PLACEHOLDER_FROM = "Sales Rep <rep@example.invalid>"
PLACEHOLDER_TO = "Prospect <prospect@example.invalid>"


def render_email_sequence(content: dict, ledger: list[dict], out_dir: Path, basename: str) -> list[Path]:
    citations = Citations(ledger)
    emails = content["emails"]
    overview = out_dir / f"{basename}.md"
    overview.write_text(_overview(emails, citations), encoding="utf-8")
    paths = [overview]
    for email in emails:
        path = out_dir / f"{basename}-step{email['step']}.eml"
        path.write_bytes(_message(email, citations).as_bytes())
        paths.append(path)
    return paths


def _single_line(text: str) -> str:
    return " ".join(text.split())


def _message(email: dict, citations: Citations) -> EmailMessage:
    message = EmailMessage(policy=SMTP)
    message["Subject"] = _single_line(email["subject"])
    message["From"] = PLACEHOLDER_FROM
    message["To"] = PLACEHOLDER_TO
    message["X-Send-Day"] = str(email["send_day"])
    message["X-Preview-Text"] = _single_line(email["preview_text"])
    message.set_content(flag_missing_markers(email["body_text"].strip(), citations) + "\n", charset="utf-8")
    return message


def _overview(emails: list[dict], citations: Citations) -> str:
    sections = ["# Email sequence"]
    for email in emails:
        body = flag_missing_markers(email["body_text"].strip(), citations)
        sections.append(
            f"## Email {email['step']} - Day {email['send_day']} - persona {email['persona_id']}\n\n"
            f"**Subject:** {email['subject']}\n\n"
            f"**Preview:** {email['preview_text']}\n\n"
            f"{body}\n\n"
            f"**Ask:** {email['ask']}"
        )
    references = references_markdown(cited_ids([e["body_text"] for e in emails], citations), citations)
    if references:
        sections.append(references.rstrip())
    return "\n\n".join(sections) + "\n"
