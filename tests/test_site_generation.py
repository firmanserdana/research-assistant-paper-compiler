import os
import json
import pytest
from src.monitor import LiteratureMonitor

@pytest.fixture
def monitor():
    return LiteratureMonitor(provider="crossref")


def test_site_generation(monitor, tmp_path):
    dummy_papers = [
        {
            'title': 'Test Paper Alpha',
            'authors': ['Author One', 'Author Two'],
            'doi': '10.1038/s41394-026-00748-y',
            'trl': 5,
            'keywords': ['EMG', 'prosthetics'],
            'summary': 'Summary for test paper alpha.',
            'category': 'EMG Decoding on Spinal Cord Injured Patients'
        },
        {
            'title': 'Test Paper Beta',
            'authors': ['Author Three'],
            'doi': '10.3390/cells10081886',
            'trl': 2,
            'keywords': ['intracortical'],
            'summary': 'Summary for test paper beta.',
            'category': 'Intracortical Decoding on Hand and Finger Kinematics'
        }
    ]

    total_count = monitor.generate_site(new_papers=dummy_papers)
    assert total_count >= 2

    assert os.path.exists('docs/index.html')
    assert os.path.exists('docs/update.json')
    assert os.path.exists('docs/feed.xml')

    with open('docs/index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    assert "Test Paper Alpha" in html
    assert "Test Paper Beta" in html
    assert 'data-title-raw="Test Paper Alpha"' in html
    assert "data-bs-theme" in html
    assert "copy-bibtex-btn" in html
    assert "btn-filter" in html
    assert "export-bibtex-btn" in html
    assert "saved-filter-btn" in html
    assert "star-btn" in html
    assert "feed.xml" in html

    with open('docs/update.json', 'r', encoding='utf-8') as f:
        update_data = json.load(f)

    assert update_data['total_count'] >= 2
    assert "categories" in update_data

