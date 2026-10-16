import pytest
from src.monitor import LiteratureMonitor

@pytest.fixture
def monitor():
    return LiteratureMonitor(provider="crossref")


def test_standard_doi(monitor):
    doi = "10.1038/s41394-026-00748-y"
    assert monitor._normalize_doi(doi) == "10.1038/s41394-026-00748-y"


def test_doi_ending_with_digits_not_truncated(monitor):
    # This was the critical bug: previously re.sub(r'\[?\d+\]?$', '', doi) stripped ending digits!
    doi = "10.3390/cells10081886"
    assert monitor._normalize_doi(doi) == "10.3390/cells10081886"

    doi2 = "10.1109/TNSRE.2024.3352847"
    assert monitor._normalize_doi(doi2) == "10.1109/TNSRE.2024.3352847"

    doi3 = "10.7759/cureus.39205"
    assert monitor._normalize_doi(doi3) == "10.7759/cureus.39205"


def test_doi_with_url_prefixes(monitor):
    assert monitor._normalize_doi("https://doi.org/10.1126/scirobotics.aax2352") == "10.1126/scirobotics.aax2352"
    assert monitor._normalize_doi("http://doi.org/10.1126/scirobotics.aax2352") == "10.1126/scirobotics.aax2352"
    assert monitor._normalize_doi("doi.org/10.1126/scirobotics.aax2352") == "10.1126/scirobotics.aax2352"
    assert monitor._normalize_doi("DOI: 10.1126/scirobotics.aax2352") == "10.1126/scirobotics.aax2352"
    assert monitor._normalize_doi("doi:10.1126/scirobotics.aax2352") == "10.1126/scirobotics.aax2352"


def test_doi_with_citation_brackets(monitor):
    # Bracketed reference citations should be stripped
    assert monitor._normalize_doi("10.3389/fnins.2025.1532099[1]") == "10.3389/fnins.2025.1532099"
    assert monitor._normalize_doi("10.3389/fnins.2025.1532099[12]") == "10.3389/fnins.2025.1532099"


def test_doi_with_trailing_punctuation(monitor):
    assert monitor._normalize_doi("10.7554/eLife.82598.") == "10.7554/eLife.82598"
    assert monitor._normalize_doi("10.7554/eLife.82598/") == "10.7554/eLife.82598"
    assert monitor._normalize_doi("10.7554/eLife.82598, ") == "10.7554/eLife.82598"


def test_doi_with_parenthetical_info(monitor):
    assert monitor._normalize_doi("10.1016/j.neuron.2024.01.012 (2024)") == "10.1016/j.neuron.2024.01.012"


def test_placeholder_dois_return_empty(monitor):
    assert monitor._normalize_doi("Not available") == ""
    assert monitor._normalize_doi("Not provided in search results") == ""
    assert monitor._normalize_doi("[Not provided in search results]") == ""
    assert monitor._normalize_doi("N/A") == ""
    assert monitor._normalize_doi("Unknown") == ""
    assert monitor._normalize_doi("See article") == ""
    assert monitor._normalize_doi("") == ""
    assert monitor._normalize_doi(None) == ""


def test_embedded_doi_extraction(monitor):
    text = "Available online at 10.1109/ICRA.2020.9196629 in proceedings"
    assert monitor._normalize_doi(text) == "10.1109/ICRA.2020.9196629"
