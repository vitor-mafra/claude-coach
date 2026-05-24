"""Thin email sender. Wraps Resend so nothing else imports the SDK directly."""

from __future__ import annotations

import structlog

import resend

from claude_coach.config import settings

log = structlog.get_logger(__name__)


class EmailError(RuntimeError):
    pass


class EmailAdapter:
    def __init__(self) -> None:
        self._key = settings.resend_api_key

    def send(self, *, subject: str, html: str, to: str | None = None) -> str:
        if not self._key:
            raise EmailError("RESEND_API_KEY not configured")
        from_email = settings.resend_from_email
        to_email = to or settings.weekly_report_to_email
        if not from_email or not to_email:
            raise EmailError(
                "Set RESEND_FROM_EMAIL and WEEKLY_REPORT_TO_EMAIL (or pass `to=`)"
            )
        resend.api_key = self._key
        params: resend.Emails.SendParams = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
        try:
            response = resend.Emails.send(params)
        except Exception as exc:
            log.error("email.send.fail", error=str(exc))
            raise EmailError(str(exc)) from exc
        email_id = response.get("id", "") if isinstance(response, dict) else str(response)
        log.info("email.sent", to=to_email, subject=subject, id=email_id)
        return email_id


adapter = EmailAdapter()


_BODY_STYLE = (
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
    "max-width: 640px; margin: 24px auto; color: #18181b; "
    "line-height: 1.55; padding: 0 16px;"
)
_H1_STYLE = (
    "font-size: 22px; font-weight: 700; color: #18181b; "
    "margin: 24px 0 12px 0;"
)
_H2_STYLE = (
    "font-size: 13px; font-weight: 700; color: #c2410c; text-transform: uppercase; "
    "letter-spacing: 0.08em; margin: 28px 0 8px 0; "
    "padding-bottom: 4px; border-bottom: 1px solid #e4e4e7;"
)
_H3_STYLE = (
    "font-size: 14px; font-weight: 700; color: #18181b; margin: 18px 0 6px 0;"
)
_UL_STYLE = "margin: 4px 0 12px 0; padding-left: 22px;"
_LI_STYLE = "margin: 2px 0;"
_P_STYLE = "margin: 6px 0;"
_CODE_STYLE = (
    "background: #f4f4f5; padding: 1px 5px; border-radius: 3px; "
    "font-family: ui-monospace, SFMono-Regular, monospace; font-size: 90%;"
)
_FOOTER_STYLE = (
    "margin-top: 36px; padding-top: 12px; border-top: 1px solid #e4e4e7; "
    "color: #71717a; font-size: 12px;"
)


def markdown_to_html(md: str) -> str:
    """Bare-bones markdown→HTML with inline styles for email clients.

    Covers headings (h1/h2/h3), bullet lists, bold, inline code, paragraphs."""
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw_line in md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            close_list()
            continue
        if line.startswith("### "):
            close_list()
            out.append(f'<h3 style="{_H3_STYLE}">{_inline(line[4:])}</h3>')
            continue
        if line.startswith("## "):
            close_list()
            out.append(f'<h2 style="{_H2_STYLE}">{_inline(line[3:])}</h2>')
            continue
        if line.startswith("# "):
            close_list()
            out.append(f'<h1 style="{_H1_STYLE}">{_inline(line[2:])}</h1>')
            continue
        if line.startswith("- "):
            if not in_list:
                out.append(f'<ul style="{_UL_STYLE}">')
                in_list = True
            out.append(f'  <li style="{_LI_STYLE}">{_inline(line[2:])}</li>')
            continue
        close_list()
        out.append(f'<p style="{_P_STYLE}">{_inline(line)}</p>')
    close_list()
    body = "\n".join(out)
    footer = (
        f'<div style="{_FOOTER_STYLE}">'
        "Enviado pelo Claude Coach. Você pode acessar o relatório completo na app."
        "</div>"
    )
    return f'<div style="{_BODY_STYLE}">{body}{footer}</div>'


def _inline(s: str) -> str:
    # **bold** and `code` — minimal subset
    out = []
    i = 0
    while i < len(s):
        if s.startswith("**", i):
            end = s.find("**", i + 2)
            if end != -1:
                out.append(
                    '<strong style="color:#18181b;">'
                    + _escape(s[i + 2 : end])
                    + "</strong>"
                )
                i = end + 2
                continue
        if s[i] == "`":
            end = s.find("`", i + 1)
            if end != -1:
                out.append(
                    f'<code style="{_CODE_STYLE}">'
                    + _escape(s[i + 1 : end])
                    + "</code>"
                )
                i = end + 1
                continue
        out.append(_escape(s[i]))
        i += 1
    return "".join(out)


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
