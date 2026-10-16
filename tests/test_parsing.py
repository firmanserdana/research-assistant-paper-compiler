import pytest
from src.monitor import LiteratureMonitor

@pytest.fixture
def monitor():
    return LiteratureMonitor(provider="crossref")


def test_parse_response_plain_text(monitor):
    sample = """Title: High-Density EMG Decoding of Dexterous Manipulation
Authors: John Doe; Jane Smith
DOI: 10.1109/TNSRE.2024.1234567
TRL: 5
Keywords: EMG, decoding, robotics
Summary: A novel framework for decoding high-density electromyography signals for robotic hand control.
"""
    papers = monitor._parse_response(sample)
    assert len(papers) == 1
    p = papers[0]
    assert p['title'] == "High-Density EMG Decoding of Dexterous Manipulation"
    assert p['authors'] == ["John Doe", "Jane Smith"]
    assert p['doi'] == "10.1109/TNSRE.2024.1234567"
    assert p['trl'] == 5
    assert "EMG" in p['keywords']
    assert "novel framework" in p['summary']


def test_parse_response_markdown_bolding(monitor):
    # LLMs frequently output markdown bolding
    sample = """**Title:** Intracortical Decoding of Finger Kinematics
**Authors:** Alice Brown, Bob Green
**DOI:** 10.1038/s41598-023-40664-x
**TRL:** 4
**Keywords:** BCI, intracortical, kinematics
**Summary:** Demonstrates single-joint level decoding from motor cortex recordings.
"""
    papers = monitor._parse_response(sample)
    assert len(papers) == 1
    p = papers[0]
    assert p['title'] == "Intracortical Decoding of Finger Kinematics"
    assert len(p['authors']) == 2
    assert p['doi'] == "10.1038/s41598-023-40664-x"
    assert p['trl'] == 4


def test_parse_response_numbered_list(monitor):
    sample = """1. Title: Paper One
Authors: Author A
DOI: 10.1016/j.neuron.2024.01.012
TRL: 3
Keywords: neural
Summary: First summary.

2. Title: Paper Two
Authors: Author B; Author C
DOI: 10.1038/s41551-024-01299-z
TRL: 6
Keywords: robotics
Summary: Second summary.
"""
    papers = monitor._parse_response(sample)
    assert len(papers) == 2
    assert papers[0]['title'] == "Paper One"
    assert papers[1]['title'] == "Paper Two"


def test_parse_response_multiline_summary(monitor):
    sample = """Title: Multiline Summary Paper
Authors: Solo Author
DOI: 10.1126/scirobotics.aax2352
TRL: 4
Keywords: sensory feedback
Summary: This is the first sentence of the summary.
Here is the second sentence providing more technical detail.
And the third sentence wrapping up the study.
"""
    papers = monitor._parse_response(sample)
    assert len(papers) == 1
    s = papers[0]['summary']
    assert "first sentence" in s
    assert "second sentence" in s
    assert "third sentence" in s


def test_parse_archive_markdown(monitor):
    markdown = """# Research Papers Compilation - March 03, 2025

## Summary
This compilation contains 2 new papers.

## EMG Decoding on Spinal Cord Injured Patients (2 papers)

### Fusion of EEG and EMG signals for detecting pre-movement intentions
**Authors:** Avi Ohry; Fatma Kumbara
**DOI:** 10.3389/fnins.2025.1532099
**TRL:** 6
**Keywords:** EEG, EMG, SCI
**Summary:** This study proposes a novel multimodal fusion method.
It achieves high accuracy under fatigue conditions.
---

### Second Paper Title
**Authors:** Nicolas Guerout
**DOI:** 10.3390/cells10081886
**TRL:** 2
**Keywords:** plasticity
**Summary:** Review examining cellular mechanisms.
---
"""
    papers = monitor._parse_archive_markdown(markdown)
    assert len(papers) == 2
    assert papers[0]['title'] == "Fusion of EEG and EMG signals for detecting pre-movement intentions"
    assert papers[0]['doi'] == "10.3389/fnins.2025.1532099"
    assert papers[0]['trl'] == 6
    assert "fatigue conditions" in papers[0]['summary']
    assert "---" not in papers[0]['summary']
    assert papers[1]['doi'] == "10.3390/cells10081886"
