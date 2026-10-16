import os
import xml.etree.ElementTree as ET
import pytest
from src.monitor import LiteratureMonitor

@pytest.fixture
def monitor():
    return LiteratureMonitor(provider="crossref")


def test_rss_feed_generation(monitor, tmp_path):
    feed_path = tmp_path / "feed.xml"
    papers = [
        {
            "title": "Biohybrid Robotic Finger with Living Muscle Actuators",
            "authors": ["Yuya Morimoto", "Hiroaki Onoe", "Shoji Takeuchi"],
            "doi": "10.1126/scirobotics.aat4440",
            "trl": 3,
            "category": "Biohybrid Systems",
            "summary": "Fabrication of an antagonistic biohybrid robot driven by living skeletal muscle.",
            "archive_date": "2026-10-15",
            "pdf_url": "https://example.com/paper.pdf"
        },
        {
            "title": "Neural Decoding of Grasping Force in Non-Human Primates",
            "authors": ["Alice Smith", "Bob Jones"],
            "doi": "10.1038/s41598-026-00001-x",
            "trl": 4,
            "category": "Intracortical Decoding on Hand and Finger Kinematics",
            "summary": "Predicting force from intracortical microelectrode arrays.",
            "archive_date": "2026-10-10",
            "pdf_url": ""
        }
    ]

    out_file = monitor._generate_rss_feed(papers, output_path=str(feed_path), max_items=10)
    assert os.path.exists(out_file)

    tree = ET.parse(out_file)
    root = tree.getroot()
    assert root.tag == "rss"
    assert root.attrib.get("version") == "2.0"

    channel = root.find("channel")
    assert channel is not None
    assert channel.find("title").text == "Biorobotics Literature Monitor"
    assert channel.find("link").text == "https://firmanserdana.github.io/research-assistant-paper-compiler/"

    items = channel.findall("item")
    assert len(items) == 2

    first_item = items[0]
    assert first_item.find("title").text == "Biohybrid Robotic Finger with Living Muscle Actuators"
    assert first_item.find("link").text == "https://doi.org/10.1126/scirobotics.aat4440"
    assert first_item.find("category").text == "Biohybrid Systems"
    assert "Yuya Morimoto" in first_item.find("description").text
    assert "https://example.com/paper.pdf" in first_item.find("description").text
