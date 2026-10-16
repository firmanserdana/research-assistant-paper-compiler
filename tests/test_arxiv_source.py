import pytest
from unittest.mock import patch, MagicMock
from src.monitor import LiteratureMonitor

SAMPLE_ARXIV_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2607.22779v1</id>
    <published>2026-07-24T09:03:09Z</published>
    <title>Multimodal Surface EMG Hand Gesture Recognition Using Transformers</title>
    <summary>We present a novel transformer model for real-time EMG decoding.</summary>
    <author>
      <name>Federico Del Pup</name>
    </author>
    <author>
      <name>Manfredo Atzori</name>
    </author>
    <arxiv:doi>10.48550/arXiv.2607.22779</arxiv:doi>
    <link title="pdf" href="https://arxiv.org/pdf/2607.22779v1" rel="related" type="application/pdf"/>
    <category term="cs.RO"/>
    <category term="q-bio.NC"/>
  </entry>
</feed>
"""

@pytest.fixture
def monitor():
    return LiteratureMonitor(provider="arxiv")


def test_arxiv_search_parsing(monitor):
    mock_response = MagicMock()
    mock_response.content = SAMPLE_ARXIV_XML
    mock_response.raise_for_status = MagicMock()

    with patch('requests.get', return_value=mock_response):
        formatted_output = monitor._arxiv_search("EMG decoding", max_results=1)

    assert "Title: Multimodal Surface EMG Hand Gesture Recognition Using Transformers" in formatted_output
    assert "Authors: Federico Del Pup; Manfredo Atzori" in formatted_output
    assert "DOI: 10.48550/arXiv.2607.22779" in formatted_output
    assert "PDF: https://arxiv.org/pdf/2607.22779.pdf" in formatted_output
    assert "TRL: 2" in formatted_output

    parsed = monitor._parse_response(formatted_output)
    assert len(parsed) == 1
    paper = parsed[0]
    assert paper['title'] == "Multimodal Surface EMG Hand Gesture Recognition Using Transformers"
    assert paper['doi'] == "10.48550/arXiv.2607.22779"
    assert paper['authors'] == ["Federico Del Pup", "Manfredo Atzori"]
    assert paper['pdf_url'] == "https://arxiv.org/pdf/2607.22779.pdf"
    assert monitor._validate(paper) is True


def test_arxiv_fallback_doi_generation(monitor):
    xml_without_doi = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.99999v2</id>
    <title>Robotic Exoskeleton Control via Neuromuscular Interface</title>
    <summary>Testing exoskeleton control.</summary>
    <author>
      <name>Jane Doe</name>
    </author>
    <category term="cs.RO"/>
  </entry>
</feed>
"""
    mock_response = MagicMock()
    mock_response.content = xml_without_doi
    mock_response.raise_for_status = MagicMock()

    with patch('requests.get', return_value=mock_response):
        text = monitor._arxiv_search("exoskeleton", max_results=1)

    assert "DOI: 10.48550/arXiv.2501.99999" in text
    assert "PDF: https://arxiv.org/pdf/2501.99999.pdf" in text
