"""Alert emails (docs/handoffs/alerts-beta.md): the senders, the signed links, and the four templates.

Senders: SMTP (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM in .env; Resend) or, without SMTP_HOST,
a log line. Templates: confirm, sign-in, deals landed (one or several, one email), expired. Every alert email has
a footer with Change alerts (/m/), Stop these emails (/u/, also the List-Unsubscribe header) and Data by Keepa.
Messages carry D19/D36 fields only and link to our site (/d/ redirects to Amazon), never to Amazon (D23).
"""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape
from typing import Callable

from . import tokens

ATTRIBUTION_URL = "https://keepa.com"
INK, INK2, STAMP, KRAFT, KRAFT_INK, GROUND, RULE = "#222326", "#45464A", "#4B3BA6", "#D9BC92", "#2A1E10", "#E6E6E2", "#ECECE8"


@dataclass
class Mail:
    subject: str
    text: str
    html: str
    headers: dict[str, str] = field(default_factory=dict)


Sender = Callable[[str, Mail], None]  # (address, mail); raises on failure


def smtp_sender(env=os.environ) -> Sender:
    host, port = env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587)
    user, password, sender = env.get("SMTP_USER"), env.get("SMTP_PASSWORD"), env.get("MAIL_FROM") or env.get("SMTP_USER")
    reply_to = env.get("MAIL_REPLY_TO")

    def send(address: str, mail: Mail) -> None:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = sender, address, mail.subject
        m["Message-ID"] = make_msgid(domain=(sender or "fiftyoff.app").rsplit("@", 1)[-1].strip("> "))
        if reply_to:
            m["Reply-To"] = reply_to
        for k, v in mail.headers.items():
            m[k] = v
        m.set_content(mail.text)
        m.add_alternative(mail.html, subtype="html")
        with (smtplib.SMTP_SSL(host, port, timeout=30) if port == 465 else smtplib.SMTP(host, port, timeout=30)) as s:
            if port != 465:
                s.starttls()
            if user:
                s.login(user, password or "")
            s.send_message(m)
    return send


def log_sender(log: Callable[[str], None] = print) -> Sender:
    def send(address: str, mail: Mail) -> None:
        log(f"[log only] to {address}: {mail.subject}\n{mail.text}")
    return send


def make_sender(env=os.environ, log: Callable[[str], None] = print) -> tuple[Sender, str]:
    return (smtp_sender(env), "smtp") if env.get("SMTP_HOST") else (log_sender(log), "log only")


# ---------------------------------------------------------------- links

@dataclass
class Links:
    """Absolute links into the site. `site` is e.g. https://beta.fiftyoff.app; `key` signs the tokens."""
    site: str
    key: str

    def _t(self, purpose: str, sid: int, iid: int | None = None) -> str:
        return tokens.sign(self.key, purpose, sid, iid)

    def confirm(self, sid: int, iid: int) -> str:
        return f"{self.site}/c/{self._t('confirm', sid, iid)}"

    def signin(self, sid: int) -> str:
        return f"{self.site}/m/{self._t('signin', sid)}"

    def manage(self, sid: int) -> str:
        return f"{self.site}/m/{self._t('manage', sid)}"

    def rearm(self, sid: int, iid: int) -> str:
        return f"{self.site}/m/{self._t('manage', sid)}?rearm={iid}"

    def stop(self, sid: int) -> str:
        return f"{self.site}/u/{self._t('stop', sid)}"

    def deal(self, slug: str) -> str:
        return f"{self.site}/d/{slug}?s=email"

    def search(self, keyword: str) -> str:
        from urllib.parse import quote
        return f"{self.site}/deals/?q={quote(keyword)}"


# ---------------------------------------------------------------- pieces

def money(cents: int | None) -> str:
    return f"${cents / 100:,.2f}" if cents is not None else ""


def grade(cond: str | None) -> str:
    return (cond or "Resale").removeprefix("Used - ")


def ago(now: datetime, t: datetime | None) -> str:
    if not t:
        return ""
    m = max(0, int((now - t).total_seconds() // 60))
    if m < 60:
        return f"{m} min ago"
    h = m // 60
    return f"{h} h ago" if h < 48 else f"{h // 24} days ago"


def _button(href: str, label: str) -> str:
    return (f'<a href="{escape(href)}" style="display:inline-block;background:{STAMP};color:#fff;text-decoration:none;'
            f'font-weight:600;padding:12px 20px;border-radius:2px">{escape(label)}</a>')


def _page(inner: str, footer: str) -> str:
    return (f'<!doctype html><html><body style="margin:0;padding:0;background:{GROUND}">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{GROUND}"><tr><td align="center" style="padding:24px 12px">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#fff;'
            f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif;color:{INK};font-size:16px;line-height:1.45">'
            f'<tr><td style="background:{KRAFT};padding:14px 24px;font-weight:900;font-size:22px;letter-spacing:.5px;color:{KRAFT_INK}">'
            f'fifty<span style="color:{STAMP}">Off</span></td></tr>'
            f'<tr><td style="padding:24px">{inner}</td></tr>'
            f'<tr><td style="padding:16px 24px 24px;border-top:1px solid {RULE};color:{INK2};font-size:13px">{footer}</td></tr>'
            f'</table></td></tr></table></body></html>')


def _footer(why: str, links: Links | None, sid: int | None) -> tuple[str, str]:
    """(text, html) footer. `links`/`sid` given: the manage and stop links (alert emails); else only the reason."""
    text = f"\n\n--\n{why}\n"
    html = f"<p style=\"margin:0 0 8px\">{escape(why)}</p>"
    if links and sid is not None:
        m, u = links.manage(sid), links.stop(sid)
        text += f"Change alerts: {m}\nStop these emails: {u}\n"
        html += (f'<p style="margin:0 0 8px"><a href="{escape(m)}" style="color:{STAMP}">Change alerts</a> · '
                 f'<a href="{escape(u)}" style="color:{STAMP}">Stop these emails</a> · '
                 f'<a href="{ATTRIBUTION_URL}" style="color:{STAMP}">Data by Keepa</a></p>')
    else:
        html += f'<p style="margin:0 0 8px"><a href="{ATTRIBUTION_URL}" style="color:{STAMP}">Data by Keepa</a></p>'
    text += f"Prices: Data by Keepa ({ATTRIBUTION_URL}). fiftyOff has no affiliate links.\n"
    html += "<p style=\"margin:0\">fiftyOff: Amazon Resale at half off or better. No affiliate links.</p>"
    return text, html


def unsubscribe_headers(links: Links, sid: int) -> dict[str, str]:
    """RFC 8058 one-click: mail apps POST `List-Unsubscribe=One-Click` to the stop link."""
    return {"List-Unsubscribe": f"<{links.stop(sid)}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


# ---------------------------------------------------------------- templates

def confirm_mail(keyword: str, links: Links, sid: int, iid: int) -> Mail:
    url = links.confirm(sid, iid)
    lead = (f"Tap below and we'll email you when '{keyword}' lands on fiftyOff at half off or better: "
            "Amazon Resale units, sold and shipped by Amazon.")
    ignore = "Didn't ask for this? Ignore it and we won't email you again."
    text = f"{lead}\n\nYes, watch '{keyword}': {url}\n\n{ignore}\nThe link works for 24 hours."
    ft, fh = _footer("You (or someone with your address) asked for alerts at fiftyoff.app.", None, None)
    html = _page(f'<p style="margin:0 0 20px">{escape(lead)}</p><p style="margin:0 0 24px">{_button(url, f"Yes, watch '{keyword}'")}</p>'
                 f'<p style="margin:0;color:{INK2};font-size:14px">{escape(ignore)} The link works for 24 hours.</p>', fh)
    return Mail(f"Confirm alerts for '{keyword}'", text + ft, html)


def signin_mail(links: Links, sid: int) -> Mail:
    url = links.signin(sid)
    lead = "Here's your link to sign in to fiftyOff and see your alerts."
    ignore = "Didn't ask for this? Ignore it; nothing changes."
    text = f"{lead}\n\nSign in: {url}\n\n{ignore}\nThe link works for 24 hours."
    ft, fh = _footer("Someone asked to sign in to fiftyoff.app with this address.", None, None)
    html = _page(f'<p style="margin:0 0 20px">{escape(lead)}</p><p style="margin:0 0 24px">{_button(url, "Sign in")}</p>'
                 f'<p style="margin:0;color:{INK2};font-size:14px">{escape(ignore)} The link works for 24 hours.</p>', fh)
    return Mail("Your fiftyOff sign-in link", text + ft, html)


def deals_mail(keyword: str, items: list[dict], links: Links, sid: int, iid: int, one_shot: bool, now: datetime) -> Mail:
    """items: title, slug, image, strict, resale_cents, ref_cents, cond, at (landed). Best % off first."""
    items = sorted(items, key=lambda i: -(i["strict"] or 0))
    one = items[0]
    pct = round(one["strict"] * 100)
    subject = (f"{keyword}: {one['title'][:70]}, {pct}% off" if len(items) == 1
               else f"{len(items)} {keyword} deals at half off or better")
    texts, blocks = [], []
    for i in items:
        p = round(i["strict"] * 100)
        usual = f" (usually {money(i.get('ref_cents'))})" if i.get("ref_cents") else ""
        line = f"{p}% off · {money(i['resale_cents'])}{usual} · {grade(i.get('cond'))}"
        when = f"Landed {ago(now, i.get('at'))} · still live when we sent this"
        url = links.deal(i["slug"])
        texts.append(f"{i['title']}\n{line}\n{when}\n{url}")
        img = (f'<a href="{escape(url)}"><img src="{escape(i["image"])}" alt="" width="120" '
               f'style="display:block;width:120px;max-height:120px;object-fit:contain;border:1px solid {RULE}"></a>') if i.get("image") else ""
        blocks.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px"><tr>'
            + (f'<td width="132" valign="top" style="padding-right:12px">{img}</td>' if img else "")
            + f'<td valign="top"><div style="font-weight:900;font-size:22px;color:{STAMP}">{p}% off</div>'
              f'<div style="margin:2px 0 6px"><a href="{escape(url)}" style="color:{INK};text-decoration:none;font-weight:600">{escape(i["title"])}</a></div>'
              f'<div style="color:{INK2};font-size:14px">{escape(money(i["resale_cents"]) + usual + " · " + grade(i.get("cond")))}</div>'
              f'<div style="color:{INK2};font-size:13px;margin:2px 0 10px">{escape(when)}</div>'
              f'{_button(url, "See the deal")}</td></tr></table>')
    intro = "Amazon Resale units like these often sell within hours."
    text = f"Your alert for '{keyword}' caught {'this' if len(items) == 1 else 'these'}. {intro}\n\n" + "\n\n".join(texts)
    html = (f'<p style="margin:0 0 20px">Your alert for <b>{escape(keyword)}</b> caught '
            f'{"this" if len(items) == 1 else "these"}. {escape(intro)}</p>' + "".join(blocks))
    if one_shot:
        again = links.rearm(sid, iid)
        text += f"\n\nThat was your free alert for '{keyword}'. Watch '{keyword}' again: {again}"
        html += (f'<p style="margin:8px 0 0;padding:14px;background:#F1F1EE">That was your free alert for '
                 f'<b>{escape(keyword)}</b>. <a href="{escape(again)}" style="color:{STAMP};font-weight:600">'
                 f'Watch {"'" + escape(keyword) + "'"} again</a></p>')
    ft, fh = _footer(f"You asked for alerts on '{keyword}' at fiftyoff.app.", links, sid)
    return Mail(subject, text + ft, _page(html, fh), unsubscribe_headers(links, sid))


def expired_mail(keyword: str, links: Links, sid: int, iid: int, days: int) -> Mail:
    again, browse = links.rearm(sid, iid), links.search(keyword)
    lead = (f"Nothing new for '{keyword}' landed at half off in the last {days} days. That usually means none came "
            "in, not that the alert broke: Resale stock comes and goes.")
    text = (f"{lead}\n\nKeep watching '{keyword}' for another {days} days: {again}\n"
            f"Or try another keyword from My alerts: {links.manage(sid)}\n\nWhat's live now: {links.site}/")
    html = (f'<p style="margin:0 0 20px">{escape(lead)}</p><p style="margin:0 0 16px">{_button(again, f"Keep watching '{keyword}'")}</p>'
            f'<p style="margin:0 0 8px"><a href="{escape(links.manage(sid))}" style="color:{STAMP}">Try another keyword</a> · '
            f'<a href="{escape(browse)}" style="color:{STAMP}">Search {"'" + escape(keyword) + "'"} now</a> · '
            f'<a href="{escape(links.site)}/" style="color:{STAMP}">What\'s live today</a></p>')
    ft, fh = _footer(f"You asked for alerts on '{keyword}' at fiftyoff.app.", links, sid)
    return Mail(f"Nothing new for '{keyword}' in {days} days", text + ft, _page(html, fh), unsubscribe_headers(links, sid))


def test_mail() -> Mail:
    t = "A test message from the fiftyOff alerts sender. Nothing to do."
    return Mail("fiftyOff test message", t, _page(f"<p>{escape(t)}</p>", "<p>Data by Keepa</p>"))
