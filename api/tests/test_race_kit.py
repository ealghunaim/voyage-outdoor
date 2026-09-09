"""Race-kit import: the HTML reader, the SSRF guard, and the narrowing.

No model is called anywhere in this file. Everything here is the part that
decides WHAT a model gets to read, which is where the interesting failures are:
a kit list flattened into one string, a page narrowed past its own equipment
section, or a URL that resolves somewhere it should not.
"""
import pytest
from fastapi import HTTPException

from api.racekit import extract, fetch

KIT_HTML = """
<html><head><title>Race</title><style>.x{color:red}</style></head>
<body>
<script>var kit = ["nope"];</script>
<h2>Mandatory equipment</h2>
<ul>
  <li>Waterproof jacket, minimum 10,000mm hydrostatic head</li>
  <li>Head torch with spare batteries</li>
  <li>Survival blanket 1.4m x 2m</li>
</ul>
<p>Poles are recommended but not compulsory.</p>
</body></html>
"""


def test_list_items_survive_as_separate_lines():
    """THE failure this reader exists to prevent. Strip tags without breaking
    on them and a kit list becomes one run-on string in which the item
    boundaries — the entire content — no longer exist."""
    text = fetch.html_to_text(KIT_HTML)
    lines = [line for line in text.split("\n") if line.strip()]
    assert "Waterproof jacket, minimum 10,000mm hydrostatic head" in lines
    assert "Head torch with spare batteries" in lines
    assert "Survival blanket 1.4m x 2m" in lines


def test_script_and_style_do_not_reach_the_model():
    text = fetch.html_to_text(KIT_HTML)
    assert "var kit" not in text
    assert "color:red" not in text


def test_entities_are_decoded():
    assert fetch.html_to_text("<p>2&nbsp;&times;&nbsp;500ml &amp; a flask</p>") \
        == "2 × 500ml & a flask"


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # cloud instance metadata
    "http://127.0.0.1:8000/v1/gear",              # this API itself
    "http://localhost/",
    "http://[::1]/",
    "http://10.0.0.5/kit",
])
def test_private_and_loopback_addresses_are_refused(url):
    """A URL typed by a user is fetched BY THIS SERVER. Without this guard the
    metadata service and the API's own loopback are both reachable, and the
    result is summarised straight back to whoever asked."""
    with pytest.raises(HTTPException) as e:
        fetch.fetch(url)
    assert e.value.status_code == 422


def test_non_http_schemes_are_refused():
    for url in ("file:///etc/passwd", "gopher://x/", "ftp://x/"):
        with pytest.raises(HTTPException) as e:
            fetch.fetch(url)
        assert e.value.status_code == 422


def test_short_page_is_sent_whole():
    body, stats = extract.narrow("mandatory equipment: jacket")
    assert stats["narrowed"] is False
    assert stats["truncated"] is False
    assert body == "mandatory equipment: jacket"


def test_long_page_keeps_the_equipment_section_not_just_the_head():
    """The equipment section of a race site is usually near the BOTTOM, under
    the results and the sponsors. Head truncation would drop exactly the part
    worth reading."""
    filler = "sponsor news and results. " * 6000
    page = ("Trans Alpine 2026 " + filler
            + "MANDATORY EQUIPMENT: waterproof jacket 10,000mm, whistle. "
            + filler)
    assert len(page) > extract.MAX_CHARS
    body, stats = extract.narrow(page)
    assert stats["narrowed"] is True
    assert "MANDATORY EQUIPMENT" in body
    assert "waterproof jacket 10,000mm" in body
    # The head is always kept: it carries the race name and edition, which are
    # provenance rather than kit.
    assert "Trans Alpine 2026" in body
    assert len(body) <= extract.MAX_CHARS + 32


def test_narrowing_is_multilingual():
    """A runner's races are not all in English. Anchoring only on 'mandatory'
    would narrow a French race page to its sponsors."""
    filler = "actualités et résultats. " * 6000
    page = filler + "MATÉRIEL OBLIGATOIRE : veste imperméable 10 000 mm. " + filler
    body, stats = extract.narrow(page)
    assert stats["narrowed"] is True
    assert "veste imperméable" in body


def test_truncation_is_reported_rather_than_silent():
    """A kit list cut off at a byte limit extracts as a SHORTER kit list, and a
    short kit list is what gets someone turned away at a check. The flag is how
    the draft can say so."""
    page = ("mandatory equipment " + "x" * 500) * 400
    _, stats = extract.narrow(page)
    assert stats["narrowed"] is True
    assert stats["truncated"] is True


def test_hex_entities_are_decoded():
    """Real pages write apostrophes as &#x27;. The decimal-only decoder shipped
    first and left the entity sitting in kit lines — "the organiser&#x27;s
    number" is a line a model would transcribe verbatim, entity and all."""
    assert fetch.html_to_text("<li>the organiser&#x27;s number &#8212; saved</li>") \
        == "the organiser's number — saved"


def test_a_javascript_shell_is_refused_before_a_model_is_paid():
    """montblanc.utmb.world returns 5,087 characters of navigation and event
    dates: the page builds itself in the browser. That sails past the
    'essentially empty' check, and the model then correctly reports no
    equipment list, having been paid to read a menu."""
    shell = ("Skip to Content UTMB World Series Events "
             "Select the event you're interested in " + "Europe 2026 " * 200)
    assert extract.has_kit_signal(shell) is False


def test_a_real_kit_page_passes_the_gate():
    assert extract.has_kit_signal("... MANDATORY EQUIPMENT ... jacket") is True
    assert extract.has_kit_signal("... MATÉRIEL OBLIGATOIRE ... veste") is True
