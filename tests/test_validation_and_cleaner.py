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


def test_estimate_trl_from_evidence(monitor):
    # Literature review -> TRL 2
    assert monitor._estimate_trl("A Literature Review of Soft Robotic Gloves", "Scoping review of soft actuators.") == 2
    # Closed-loop human prosthesis in amputees -> TRL 6
    assert monitor._estimate_trl(
        "Closed-loop bionic hand with biomimetic sensory feedback in amputees",
        "Demonstrated real-time prosthetic control in human participants with upper-limb amputation."
    ) == 6
    # Take-home clinical trial -> TRL 7
    assert monitor._estimate_trl(
        "Long-term home use of a peripheral nerve interface in amputees",
        "Take-home clinical trial during daily life activities."
    ) == 7
    # Preserve explicit high TRL (> 2)
    assert monitor._estimate_trl("Any title", "Any summary", current_trl=8) == 8


def test_extract_modalities_and_related_papers(monitor):
    p1 = {
        "title": "High-density surface EMG decoding in tetraplegic spinal cord injured patients",
        "summary": "Convolutional neural network for myoelectric hand control.",
        "keywords": ["sEMG", "spinal cord injury", "deep learning"],
        "category": "EMG Decoding on Spinal Cord Injured Patients",
        "doi": "10.1000/test1",
        "trl": 6
    }
    p2 = {
        "title": "Surface electromyography motor unit decomposition after spinal cord injury",
        "summary": "Real-time sEMG decoding in patients with tetraplegia.",
        "keywords": ["sEMG", "spinal cord injury", "motor units"],
        "category": "EMG Decoding on Spinal Cord Injured Patients",
        "doi": "10.1000/test2",
        "trl": 5
    }
    p1["modalities"] = monitor._extract_modalities(p1)
    p2["modalities"] = monitor._extract_modalities(p2)
    assert "Human / Clinical" in p1["modalities"]
    assert "Surface / HD-sEMG" in p1["modalities"]

    monitor._compute_related_papers([p1, p2], top_k=2)
    assert len(p1["related_papers"]) == 1
    assert p1["related_papers"][0]["doi"] == "10.1000/test2"


def test_reconstruct_openalex_abstract(monitor):
    inv = {"Neural": [0], "decoding": [1], "enables": [2], "dexterous": [3], "control.": [4]}
    assert monitor._reconstruct_openalex_abstract(inv) == "Neural decoding enables dexterous control."



