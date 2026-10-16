import sys
import pytest
from unittest.mock import patch
from src.monitor import LiteratureMonitor, parse_args

def test_parse_args_defaults():
    with patch.object(sys, 'argv', ['monitor.py']):
        args = parse_args()
        assert args.provider == "auto"
        assert args.dry_run is False
        assert args.limit is None
        assert args.skip_zotero is False
        assert args.include_arxiv is False


def test_parse_args_custom_flags():
    test_argv = [
        'monitor.py',
        '--provider', 'arxiv',
        '--term', 'soft robotic gripper',
        '--term', 'EMG prosthetic hand',
        '--limit', '5',
        '--dry-run',
        '--skip-zotero',
        '--include-arxiv',
        '--generate-site-only'
    ]
    with patch.object(sys, 'argv', test_argv):
        args = parse_args()
        assert args.provider == "arxiv"
        assert args.term == ['soft robotic gripper', 'EMG prosthetic hand']
        assert args.limit == 5
        assert args.dry_run is True
        assert args.skip_zotero is True
        assert args.include_arxiv is True
        assert args.generate_site_only is True


def test_dry_run_skips_archive_and_zotero():
    monitor = LiteratureMonitor(provider="arxiv", dry_run=True, skip_zotero=True)
    assert monitor.dry_run is True
    assert monitor.zot is None

    with patch.object(monitor, '_deep_research_query', return_value=("test term", "")):
        with patch.object(monitor, '_create_archive_file') as mock_archive:
            with patch.object(monitor, 'generate_site') as mock_site:
                res = monitor.execute()
                assert res == []
                mock_archive.assert_not_called()
                mock_site.assert_not_called()
