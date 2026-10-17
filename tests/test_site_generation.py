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

    out_dir = str(tmp_path)
    total_count = monitor.generate_site(new_papers=dummy_papers, output_dir=out_dir)
    assert total_count >= 2

    index_file = os.path.join(out_dir, 'index.html')
    update_file = os.path.join(out_dir, 'update.json')
    rss_file = os.path.join(out_dir, 'feed.xml')

    assert os.path.exists(index_file)
    assert os.path.exists(update_file)
    assert os.path.exists(rss_file)

    with open(index_file, 'r', encoding='utf-8') as f:
        html = f.read()

    assert "Test Paper Alpha" in html
    assert "Test Paper Beta" in html
    assert 'data-title-raw="Test Paper Alpha"' in html
    assert "analytics-drawer" in html
    assert "modality-pill" in html
    assert "related-paper-link" in html
    assert "data-bs-theme" in html
    assert "copy-bibtex-btn" in html
    assert "btn-filter" in html
    assert "export-bibtex-btn" in html
    assert "saved-filter-btn" in html
    assert "star-btn" in html
    assert "feed.xml" in html

    with open(update_file, 'r', encoding='utf-8') as f:
        update_data = json.load(f)

    assert update_data['total_count'] >= 2
    assert "categories" in update_data
    assert "trl_buckets" in update_data
    assert "total_citations" in update_data


