"""
Gmail outreach helpers for The Underline sequences.

Thread policy (Lia / June 2026):
- Emails 1–3: same Gmail thread (reply in-thread).
- Emails 4–5: new thread (fresh subject; no In-Reply-To).
"""
from __future__ import annotations

import base64
import html
import os
import re
from email.message import EmailMessage
from typing import Any, Dict, Optional, Tuple

DECK_LINK = os.getenv("UNDERLINE_DECK_LINK", "").strip()


def venue_rental_email1_subject(company_name: str) -> str:
    company_text = company_name.strip() or "your team"
    return f"The Underline Miami + {company_text}"


def make_venue_rental_email1_body(
    first_name: str,
    company_name: str = "",
    deck_link: str = "",
) -> Tuple[str, str]:
    """
    Venue rental first-touch (Lia / Aug 2026).
    Deck is hyperlinked on the words "The Underline" in the intro paragraph.
    Signature is appended by the Gmail sender (Frenchy's mailbox default).
    """
    del company_name  # subject uses company; body is name-only personalization
    customer_name = first_name.strip() or "there"
    deck_url = (deck_link or DECK_LINK).strip()

    text_underline = (
        f"The Underline ({deck_url})" if deck_url else "The Underline [DECK LINK]"
    )
    text_body = (
        f"Hi {customer_name},\n\n"
        "I'm reaching out to introduce The Underline as a potential venue for upcoming "
        "events and brand activations.\n\n"
        f"{text_underline} is Miami's 10-mile linear park, connecting Brickell, Coconut Grove, "
        "Coral Gables, the University of Miami and South Miami, with more than 3 million "
        "annual visitors.\n\n"
        "The spaces along the park range from outdoor fitness centers, playgrounds and "
        "sculpture gardens to plazas, trails and larger gathering areas that can accommodate:\n\n"
        "Corporate and community events\n"
        "Fitness and wellness programming\n"
        "Concerts and cultural events\n"
        "Dinners and culinary experiences\n"
        "Brand activations and product launches\n\n"
        "The Underline has hosted programming ranging from concert series and run clubs to "
        "The Longest Table, here are a few examples.\n\n"
        "• Lululemon Global Run Day 5K & Wellness Party — 600 attendees, DJ, cold plunges, "
        "brand activation buildouts\n"
        "• Porsche VIP Event — 200 VIP guests including civic leaders\n"
        "• Inter Brazil Day — Festival with 6,000+ attendees, vendors, family activities, "
        "and full street management\n"
        "• Baptist Health Bounce Back From Cancer — Legacy run/walk led by Miami Heat icons "
        "with 1,500+ participants\n"
        "• Adidas Tumbao — Cultural music experience\n"
        "• Let's Get Together Market — Community retail + lifestyle programming\n\n"
        "I'd be happy to share more and explore whether any of the spaces could work for "
        "events you are currently planning.\n\n"
        "Best,\n"
    )

    if deck_url:
        underline_html = (
            f'<a href="{html.escape(deck_url)}">The Underline</a>'
        )
    else:
        underline_html = "The Underline"

    html_body = (
        f"<p>Hi {html.escape(customer_name)},</p>"
        "<p>I'm reaching out to introduce The Underline as a potential venue for upcoming "
        "events and brand activations.</p>"
        f"<p>{underline_html} is Miami's 10-mile linear park, connecting Brickell, Coconut Grove, "
        "Coral Gables, the University of Miami and South Miami, with more than 3 million "
        "annual visitors.</p>"
        "<p>The spaces along the park range from outdoor fitness centers, playgrounds and "
        "sculpture gardens to plazas, trails and larger gathering areas that can accommodate:</p>"
        "<ul>"
        "<li>Corporate and community events</li>"
        "<li>Fitness and wellness programming</li>"
        "<li>Concerts and cultural events</li>"
        "<li>Dinners and culinary experiences</li>"
        "<li>Brand activations and product launches</li>"
        "</ul>"
        "<p>The Underline has hosted programming ranging from concert series and run clubs to "
        "The Longest Table, here are a few examples.</p>"
        "<ul>"
        "<li><strong>Lululemon Global Run Day 5K &amp; Wellness Party</strong> — 600 attendees, "
        "DJ, cold plunges, brand activation buildouts</li>"
        "<li><strong>Porsche VIP Event</strong> — 200 VIP guests including civic leaders</li>"
        "<li><strong>Inter Brazil Day</strong> — Festival with 6,000+ attendees, vendors, "
        "family activities, and full street management</li>"
        "<li><strong>Baptist Health Bounce Back From Cancer</strong> — Legacy run/walk led by "
        "Miami Heat icons with 1,500+ participants</li>"
        "<li><strong>Adidas Tumbao</strong> — Cultural music experience</li>"
        "<li><strong>Let's Get Together Market</strong> — Community retail + lifestyle "
        "programming</li>"
        "</ul>"
        "<p>I'd be happy to share more and explore whether any of the spaces could work for "
        "events you are currently planning.</p>"
        "<p>Best,</p>"
    )
    return text_body, html_body


def concert_series_email1_subject(company_name: str) -> str:
    company_text = company_name.strip() or "your team"
    return f"The Underline + {company_text} | Miami Music Series"


def make_concert_series_email1_body(
    first_name: str,
    company_name: str = "",
    deck_link: str = "",
) -> Tuple[str, str]:
    """
    Concert Series first-touch (Miami Music Series). No deck URL — CTA is share the deck.
    Signature is appended by the Gmail sender (Frenchy's mailbox default).
    """
    del deck_link  # Email 1 does not embed the series deck
    customer_name = first_name.strip() or "there"
    company_text = company_name.strip() or "your team"

    text_body = (
        f"Hi {customer_name},\n\n"
        "I'm reaching out to introduce The Underline's Miami Music Series, a new live music "
        "platform featuring free public concerts and larger festival experiences.\n\n"
        "The Underline is a 10-mile cultural destination connecting Brickell, Coconut Grove, "
        "Coral Gables, University of Miami, and South Miami through public spaces, arts, "
        "wellness, and community programming.\n\n"
        "Our 2026 lineup includes a Caribbean Carnival Concert in early October, followed by "
        "The Underline Festival on October 30-31, featuring 6 concerts across our onsite venues.\n\n"
        f"We think {company_text} could be a great fit for the series. Partnership opportunities "
        "can include event branding, on-site activations, VIP hospitality, food and beverage "
        "integrations, concessions, and digital content.\n\n"
        "I'd love to share the deck and explore how we could collab now or in the future.\n\n"
        "Best,\n"
    )

    html_body = (
        f"<p>Hi {html.escape(customer_name)},</p>"
        "<p>I'm reaching out to introduce The Underline's Miami Music Series, a new live music "
        "platform featuring free public concerts and larger festival experiences.</p>"
        "<p>The Underline is a 10-mile cultural destination connecting Brickell, Coconut Grove, "
        "Coral Gables, University of Miami, and South Miami through public spaces, arts, "
        "wellness, and community programming.</p>"
        "<p>Our 2026 lineup includes a Caribbean Carnival Concert in early October, followed by "
        "The Underline Festival on October 30-31, featuring 6 concerts across our onsite venues.</p>"
        f"<p>We think {html.escape(company_text)} could be a great fit for the series. Partnership "
        "opportunities can include event branding, on-site activations, VIP hospitality, food and "
        "beverage integrations, concessions, and digital content.</p>"
        "<p>I'd love to share the deck and explore how we could collab now or in the future.</p>"
        "<p>Best,</p>"
    )
    return text_body, html_body


def make_email2_body(first_name: str, company_name: str, deck_link: str = "") -> Tuple[str, str]:
    customer_name = first_name.strip() or "there"
    company_text = company_name.strip() or "your team"
    deck_url = (deck_link or DECK_LINK).strip()
    deck_text = deck_url if deck_url else "[DECK LINK]"

    text_body = (
        f"Hi {customer_name},\n\n"
        f"Circling back on my note about {company_text} and The Underline.\n\n"
        "In case it helps before a call: the park sees about 2M visitors a year. "
        "Right now we're building out a handful of specific integrations — Urban Gym, playground, "
        "River Room, seasonal programming — rather than generic \"logo on a banner\" packages.\n\n"
        f"I dropped our brand deck here: {deck_text}\n\n"
        "Would 15 minutes next week work, or is there someone else I should reach?\n\n"
        "Thanks,\n"
    )

    deck_html = f'<a href="{html.escape(deck_url)}">here</a>' if deck_url else html.escape(deck_text)
    html_body = (
        f"<p>Hi {html.escape(customer_name)},</p>"
        f"<p>Circling back on my note about {html.escape(company_text)} and <strong>The Underline</strong>.</p>"
        "<p>In case it helps before a call: the park sees about 2M visitors a year. "
        "Right now we're building out a handful of specific integrations — Urban Gym, playground, "
        "River Room, seasonal programming — rather than generic \"logo on a banner\" packages.</p>"
        f"<p>I dropped our brand deck {deck_html}.</p>"
        "<p>Would 15 minutes next week work, or is there someone else I should reach?</p>"
        "<p>Thanks,</p>"
    )
    return text_body, html_body


def make_email3_body(first_name: str, company_name: str) -> Tuple[str, str]:
    customer_name = first_name.strip() or "there"
    company_text = company_name.strip() or "your team"

    text_body = (
        f"Hi {customer_name},\n\n"
        "Wanted to bump this once in case it landed on a busy week.\n\n"
        f"We're lining up a few partners for activations this year — events, programming, and on-site "
        f"presence along the corridor. Lululemon and Chewy are examples of the kind of fit we have in mind "
        f"for {company_text}.\n\n"
        "Deck is in my last note if useful. Open to a quick call, or happy to be pointed to the right person if you're not the one.\n\n"
        "Thanks,\n"
    )
    html_body = (
        f"<p>Hi {html.escape(customer_name)},</p>"
        "<p>Wanted to bump this once in case it landed on a busy week.</p>"
        f"<p>We're lining up a few partners for activations this year — events, programming, and on-site "
        f"presence along the corridor. Lululemon and Chewy are examples of the kind of fit we have in mind "
        f"for {html.escape(company_text)}.</p>"
        "<p>Deck is in my last note if useful. Open to a quick call, or happy to be pointed to the right person if you're not the one.</p>"
        "<p>Thanks,</p>"
    )
    return text_body, html_body


def make_email4_body(first_name: str, company_name: str) -> Tuple[str, str]:
    customer_name = first_name.strip() or "there"
    company_text = company_name.strip() or "your team"

    text_body = (
        f"Hi {customer_name},\n\n"
        "Checking in one more time on The Underline — totally understand if the timing isn't right.\n\n"
        f"If {company_text} might be interested later in the year, I'm glad to stay in touch. "
        "If not, a quick \"not us\" or an intro to whoever handles experiential or brand partnerships "
        "would save us both some inbox noise.\n\n"
        "Either way, appreciate it.\n\n"
        "Thanks,\n"
    )
    html_body = (
        f"<p>Hi {html.escape(customer_name)},</p>"
        "<p>Checking in one more time on <strong>The Underline</strong> — totally understand if the timing isn't right.</p>"
        f"<p>If {html.escape(company_text)} might be interested later in the year, I'm glad to stay in touch. "
        "If not, a quick \"not us\" or an intro to whoever handles experiential or brand partnerships "
        "would save us both some inbox noise.</p>"
        "<p>Either way, appreciate it.</p>"
        "<p>Thanks,</p>"
    )
    return text_body, html_body


def make_email5_body(first_name: str, company_name: str, deck_link: str = "") -> Tuple[str, str]:
    customer_name = first_name.strip() or "there"
    company_text = company_name.strip() or "your team"
    deck_url = (deck_link or DECK_LINK).strip()
    deck_text = deck_url if deck_url else "[DECK LINK]"

    text_body = (
        f"Hi {customer_name},\n\n"
        f"I'll assume this isn't the right moment for {company_text} and won't keep filling your inbox.\n\n"
        f"If things shift — or if there's a better contact for Miami brand work — I'm easy to reach. "
        f"Deck's still here: {deck_text}\n\n"
        "Thanks for your time.\n\n"
        "Best,\n"
    )
    deck_html = deck_text if not deck_url else f'<a href="{html.escape(deck_url)}">{html.escape(deck_text)}</a>'
    html_body = (
        f"<p>Hi {html.escape(customer_name)},</p>"
        f"<p>I'll assume this isn't the right moment for {html.escape(company_text)} and won't keep filling your inbox.</p>"
        f"<p>If things shift — or if there's a better contact for Miami brand work — I'm easy to reach. "
        f"Deck's still here: {deck_html}</p>"
        "<p>Thanks for your time.</p>"
        "<p>Best,</p>"
    )
    return text_body, html_body


def default_new_thread_subject(company_name: str, email_number: int) -> str:
    company_text = company_name.strip() or "your team"
    if email_number >= 5:
        return f"Closing the loop — {company_text}"
    return f"Quick follow-up — {company_text} + The Underline (Miami)"


def send_gmail_message(
    gmail_service,
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    signature_html: str,
    thread_id: Optional[str] = None,
    in_reply_to_message_id: Optional[str] = None,
):
    msg = EmailMessage()
    msg["To"] = to_email
    msg["Subject"] = subject

    if in_reply_to_message_id:
        msg["In-Reply-To"] = in_reply_to_message_id
        msg["References"] = in_reply_to_message_id

    msg.set_content(text_body)
    final_html = html_body
    if signature_html.strip():
        final_html = f"{html_body}{signature_html}"
    msg.add_alternative(final_html, subtype="html")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    payload: Dict[str, Any] = {"raw": raw}
    if thread_id and in_reply_to_message_id:
        payload["threadId"] = thread_id

    return gmail_service.users().messages().send(userId="me", body=payload).execute()


def send_reply_in_thread(
    gmail_service,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    signature_html: str,
    thread_id: str,
    in_reply_to_message_id: str,
):
    subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    return send_gmail_message(
        gmail_service,
        to_email=to_email,
        subject=subj,
        text_body=text_body,
        html_body=html_body,
        signature_html=signature_html,
        thread_id=thread_id,
        in_reply_to_message_id=in_reply_to_message_id,
    )


def send_new_thread(
    gmail_service,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    signature_html: str,
):
    return send_gmail_message(
        gmail_service,
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        signature_html=signature_html,
    )
