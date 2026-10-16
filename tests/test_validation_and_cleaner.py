import pytest
from src.monitor import LiteratureMonitor

@pytest.fixture
def monitor():
    return LiteratureMonitor(provider="crossref")


def test_validate_valid_paper(monitor):
    paper = {
        'title': 'A Valid Biorobotics Paper Title',
        'authors': ['Jane Doe', 'John Smith'],
        'doi': '10.1038/s41394-026-00748-y',
        'trl': 3,
        'keywords': ['EMG', 'Robotics']
    }
    assert monitor._validate(paper) is True


def test_validate_rejects_missing_title(monitor):
    paper = {
        'title': '',
        'authors': ['Jane Doe'],
        'doi': '10.1038/s41394-026-00748-y',
        'trl': 3
    }
    assert monitor._validate(paper) is False


def test_validate_rejects_missing_doi(monitor):
    paper = {
        'title': 'A Valid Title Here',
        'authors': ['Jane Doe'],
        'doi': 'Not available',
        'trl': 3
    }
    assert monitor._validate(paper) is False


def test_validate_rejects_placeholder_authors(monitor):
    paper = {
        'title': 'A Valid Title Here',
        'authors': ['Not specified in search results'],
        'doi': '10.1038/s41394-026-00748-y',
        'trl': 3
    }
    assert monitor._validate(paper) is False


def test_clean_jats_abstract(monitor):
    raw = "<jats:p>This study investigated <jats:italic>in vivo</jats:italic> neural interfaces &amp; prosthetics.</jats:p>"
    clean = monitor._clean_jats_abstract(raw)
    assert "<jats" not in clean
    assert "</jats" not in clean
    assert "&amp;" not in clean
    assert "in vivo neural interfaces & prosthetics." in clean


def test_normalize_category(monitor):
    assert monitor._normalize_category("Emg decoding on spinal cord injured patients") == "EMG Decoding on Spinal Cord Injured Patients"
    assert monitor._normalize_category("intracortical decoding on hand and finger kinematics") == "Intracortical Decoding on Hand and Finger Kinematics"
    assert monitor._normalize_category("") == "General Biorobotics"
    assert monitor._normalize_category(None) == "General Biorobotics"
