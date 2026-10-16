#!/usr/bin/env python3
"""
Regenerate the GitHub Pages site and update.json using all papers from archives.
Can be run standalone at any time to refresh the docs/ folder.
"""

import sys
import logging
from src.monitor import LiteratureMonitor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('regenerate_site')


def main():
    print("=" * 60)
    print("REGENERATING LITERATURE MONITOR WEBSITE")
    print("=" * 60)

    try:
        monitor = LiteratureMonitor(provider="crossref")
        total_papers = monitor.generate_site(new_papers=[])
        print(f"Successfully generated docs/index.html and docs/update.json with {total_papers} papers.")
        print("Site regeneration complete!")
        return 0
    except Exception as e:
        logger.error(f"Failed to regenerate site: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
