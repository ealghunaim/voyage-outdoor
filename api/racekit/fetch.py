"""Fetching a race page — the part that has nothing to do with AI.

A URL typed by a user and fetched by this server is an SSRF surface. On Render
that is not theoretical: `http://169.254.169.254/` is answered by the instance
metadata service, and `http://localhost:8000/v1/gear` is answered by this API
itself. Both would be fetched, converted to text, and handed to a model that
summarises them back to the person who asked. Every guard below exists because
of one of those.

WHY THE SERVER FETCHES AT ALL rather than the phone. The extraction has to run
server-side regardless (the model key is not in the app), and a page fetched by
the phone would then have to be uploaded anyway — at which point the app is
posting arbitrary HTML to the API and the provenance record says "the user says
this came from that URL". Fetching here means the stored `source_url` and
`content_sha256` describe bytes this server actually saw.

There is no JavaScript execution here, which means script-rendered race sites
return nothing useful. That is why paste is a first-class path and not a
fallback: for a lot of races, copying the equipment section is faster and more
reliable than any fetch.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from api.core.config import settings

MAX_REDIRECTS = 5

#: Text-ish only. A PDF kit list is common and NOT handled: a binary run through
#: a tag-stripper produces plausible-looking mojibake, and a model asked to
#: extract a kit list from mojibake will produce a kit list. Refusing is the
#: safe answer; the paste path handles it in one copy.
OK_CONTENT = ("text/html", "application/xhtml", "text/plain")


@dataclass(frozen=True)
class Fetched:
    url: str                 # the FINAL url, after redirects
    text: str
    sha256: str
    bytes_read: int


def _public_ip(host: str) -> None:
    """Every address the hostname resolves to must be on the public internet.

    Checked across ALL results, not just the first: a host with one public A
    record and one 127.0.0.1 record would otherwise pass and then be dialled on
    whichever address the connection happens to pick.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(422, f"Could not resolve {host}.")
    for info in infos:
        raw = info[4][0]
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if not addr.is_global:
            # The reason is deliberately not echoed back in detail. "10.0.0.4 is
            # private" confirms to a prober what resolves where inside the
            # network; the user with a legitimate URL does not need the address.
            raise HTTPException(
                422, "That address is not on the public internet, so it will "
                     "not be fetched. Paste the equipment list instead.")


def _check(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(422, "Give an http:// or https:// address.")
    if not parsed.hostname:
        raise HTTPException(422, "That does not look like a web address.")
    _public_ip(parsed.hostname)
    return url


def fetch(url: str) -> Fetched:
    """GET a page, following redirects with the guard re-applied at every hop.

    httpx's own `follow_redirects=True` would check the first URL and then
    happily follow a 302 to the metadata service, which is exactly the bypass
    the guard exists to stop. So redirects are followed by hand.
    """
    url = _check(url.strip())
    headers = {
        # Identifying rather than disguised. A race organiser who wants to block
        # this should be able to, and pretending to be Chrome to get around that
        # is not a thing to build into a product.
        "User-Agent": "VoyageOutdoor/0.4 (race kit importer)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
    }
    limit = settings.race_kit_max_bytes

    with httpx.Client(follow_redirects=False,
                      timeout=settings.race_kit_fetch_timeout_s) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", url, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(422, "That page redirected nowhere.")
                        url = _check(str(response.url.join(location)))
                        continue

                    if response.status_code >= 400:
                        raise HTTPException(
                            422, f"That page returned HTTP {response.status_code}.")

                    ctype = (response.headers.get("content-type") or "").lower()
                    if not any(ok in ctype for ok in OK_CONTENT):
                        raise HTTPException(
                            422,
                            f"That link is {ctype.split(';')[0] or 'not a web page'}, "
                            f"which cannot be read here. Open it and paste the "
                            f"equipment section instead.")

                    chunks, total = [], 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > limit:
                            # Stop reading rather than truncate silently. A kit
                            # list cut off at the byte limit extracts as a
                            # SHORTER kit list, and a short kit list is the
                            # failure mode that gets someone turned away at a
                            # check.
                            raise HTTPException(
                                422, "That page is too large to read. Paste the "
                                     "equipment section instead.")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
            except HTTPException:
                raise
            except httpx.HTTPError as e:
                raise HTTPException(502, f"Could not fetch that page ({type(e).__name__}).")

            body = raw.decode(response.encoding or "utf-8", errors="replace")
            text = html_to_text(body)
            if len(text.split()) < 20:
                raise HTTPException(
                    422,
                    "That page came back essentially empty — it probably builds "
                    "itself in the browser. Open it and paste the equipment "
                    "section instead.")
            return Fetched(url=url, text=text,
                           sha256=hashlib.sha256(raw).hexdigest(),
                           bytes_read=total)

    raise HTTPException(422, "That page redirected too many times.")


# ── HTML → text ─────────────────────────────────────────────────────────────

_DROP = re.compile(r"<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>",
                   re.I | re.S)
#: Tags that END A LINE. This is the whole reason this is not a one-line regex.
#: A mandatory kit list is a <ul> of <li>, and stripping tags without breaking
#: on them yields "waterproof jacketwhistlesurvival blanket" — one run-on string
#: in which the item boundaries, which are the entire content, no longer exist.
_BREAK = re.compile(r"</?(br|p|div|li|tr|h[1-6]|table|ul|ol|section|article)\b[^>]*>",
                    re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANK = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t ]+")

_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
             "&quot;": '"', "&#39;": "'", "&apos;": "'", "&mdash;": "—",
             "&ndash;": "–", "&deg;": "°", "&times;": "×", "&hellip;": "…"}


def html_to_text(html: str) -> str:
    text = _DROP.sub(" ", html)
    text = _BREAK.sub("\n", text)
    text = _TAG.sub(" ", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK.sub("\n\n", "\n".join(line for line in lines if line)).strip()
