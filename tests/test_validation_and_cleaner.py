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


def test_title_similarity_matching():
    from verify_dois import compute_title_similarity
    t1 = "Fusion of EEG and EMG signals for detecting pre-movement intentions in sitting and standing"
    t2 = "Fusion of EEG and EMG signals for detecting pre-movement intention of sitting and standing in healthy individuals and patients with spinal cord injury"
    sim = compute_title_similarity(t1, t2)
    assert sim >= 0.70

    # Test hallucinated mismatch (e.g. soil mechanics vs neural prosthetics)
    fake_t = "Estimation of soil water characteristics using neural networks"
    sim_fake = compute_title_similarity(t1, fake_t)
    assert sim_fake < 0.40


def test_is_relevant_to_biorobotics(monitor):
    assert monitor._is_relevant_to_biorobotics(
        "Surface EMG in Subacute and Chronic Care after Traumatic Spinal Cord Injuries",
        "Examines surface electromyography and motor recovery."
    ) is True
    assert monitor._is_relevant_to_biorobotics(
        "Intracortical neural decoding of dexterous finger kinematics",
        "Brain-computer interface for prosthetic hand control."
    ) is True
    # Off-topic clinical case reports must be rejected
    assert monitor._is_relevant_to_biorobotics(
        "Assessment of Spinal Cord Injured Patients' Adherence toward Clean Intermittent Self-Catheterization",
        "Clinical survey on urinary self-catheterization."
    ) is False
    assert monitor._is_relevant_to_biorobotics(
        "Venous flap for immediate reconstruction of finger soft tissue defect",
        "Surgical reconstruction of finger trauma."
    ) is False
    assert monitor._is_relevant_to_biorobotics(
        "Using midodrine to accelerate weaning of intravenous vasopressors in acute spinal cord injured patients",
        "Retrospective ICU study."
    ) is False


def test_clean_citation_artifacts(monitor):
    raw = "High-density EMG decoding achieved 94.2% accuracy [1][2] in tetraplegic participants [3, 4]."
    cleaned = monitor._clean_citation_artifacts(raw)
    assert "[1]" not in cleaned
    assert "[3, 4]" not in cleaned
    assert "94.2% accuracy in tetraplegic participants." in cleaned


