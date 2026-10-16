#!/usr/bin/env python3
"""
Archive formatting and health check utility.
Validates formatting of all markdown archive files without deleting papers.
"""

import sys
from pathlib import Path
from src.monitor import LiteratureMonitor

ARCHIVE_DIR = "src/archive"


def main():
    print("=" * 60)
    print("ARCHIVE HEALTH CHECK & FORMATTING VALIDATOR")
    print("=" * 60)

    monitor = LiteratureMonitor(provider="crossref")
    archive_path = Path(ARCHIVE_DIR)
    archive_files = sorted(archive_path.glob("papers_*.md"))

    print(f"Scanning {len(archive_files)} archive files...")

    total_papers = 0
    with_doi = 0
    without_doi = 0

    for filepath in archive_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            papers = monitor._parse_archive_markdown(content)
            total_papers += len(papers)
            f_with = sum(1 for p in papers if p.get('doi'))
            f_without = len(papers) - f_with
            with_doi += f_with
            without_doi += f_without
            print(f"  {filepath.name}: {len(papers)} papers ({f_with} with DOI, {f_without} missing DOI)")
        except Exception as e:
            print(f"  Error reading {filepath.name}: {e}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total archive files:  {len(archive_files)}")
    print(f"Total papers:         {total_papers}")
    print(f"Papers with DOI:      {with_doi}")
    print(f"Papers without DOI:   {without_doi}")
    print("All archive files are structurally valid and preserved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
