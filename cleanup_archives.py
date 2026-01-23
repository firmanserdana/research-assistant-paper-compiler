#!/usr/bin/env python3
"""
Clean up fake papers from archive files based on verification report.
Replaces each archive file with a cleaned version showing only verified papers.
"""

import os
import json
from pathlib import Path
from datetime import datetime

ARCHIVE_DIR = "src/archive"
REPORT_FILE = "doi_verification_report.json"

def load_report():
    with open(REPORT_FILE, 'r') as f:
        return json.load(f)

def create_cleaned_archive(source_file, verified_papers, fake_papers):
    """Create a cleaned archive file showing verification status."""
    
    verified_in_file = [p for p in verified_papers if p.get('source_file') == source_file]
    fake_in_file = [p for p in fake_papers if p.get('source_file') == source_file]
    
    # Extract date from filename
    date_part = source_file.replace("papers_", "").replace(".md", "")
    
    content = f"""# Research Papers Compilation - {date_part}

## Summary
DOI verification completed on {datetime.now().strftime('%Y-%m-%d')}:
- Verified papers: {len(verified_in_file)}
- Fake/Invalid papers removed: {len(fake_in_file)}

"""

    if verified_in_file:
        content += "## Verified Papers\n\n"
        for paper in verified_in_file:
            content += f"### {paper['title']}\n\n"
            content += f"**Authors:** {paper.get('authors', 'N/A')}\n\n"
            content += f"**DOI:** {paper.get('doi', 'N/A')}\n\n"
            details = paper.get('verification_details', {})
            if isinstance(details, dict):
                content += f"**Verified Title:** {details.get('real_title', 'N/A')}\n\n"
                content += f"**Verified Authors:** {', '.join(details.get('real_authors', []))}\n\n"
            content += "---\n\n"
    else:
        content += "*No verified papers in this archive.*\n\n"
    
    if fake_in_file:
        content += "## Removed Papers (Fake/Invalid DOIs)\n\n"
        content += "| Title | DOI |\n|-------|-----|\n"
        for paper in fake_in_file:
            title = paper['title'][:50] + "..." if len(paper['title']) > 50 else paper['title']
            content += f"| {title} | {paper.get('doi', 'N/A')} |\n"
        content += "\n"
    
    return content

def main():
    print("=" * 60)
    print("CLEANING FAKE PAPERS FROM ARCHIVES")
    print("=" * 60)
    
    report = load_report()
    
    print(f"\nSummary from report:")
    print(f"  Total papers: {report['summary']['total']}")
    print(f"  Verified: {report['summary']['verified']}")
    print(f"  Fake: {report['summary']['fake']}")
    
    verified_papers = report.get('verified_papers', [])
    fake_papers = report.get('fake_papers', [])
    
    # Get all unique source files
    all_files = set()
    for p in verified_papers + fake_papers:
        if p.get('source_file'):
            all_files.add(p['source_file'])
    
    print(f"\n  Files to process: {len(all_files)}")
    print("-" * 60)
    
    for filename in sorted(all_files):
        filepath = Path(ARCHIVE_DIR) / filename
        
        verified_count = len([p for p in verified_papers if p.get('source_file') == filename])
        fake_count = len([p for p in fake_papers if p.get('source_file') == filename])
        
        print(f"Processing {filename}: {verified_count} verified, {fake_count} fake")
        
        content = create_cleaned_archive(filename, verified_papers, fake_papers)
        
        with open(filepath, 'w') as f:
            f.write(content)
    
    print("\n" + "=" * 60)
    print("CLEANUP COMPLETE")
    print("=" * 60)
    print(f"Processed {len(all_files)} archive files")
    print(f"Total verified papers retained: {len(verified_papers)}")
    print(f"Total fake papers removed: {len(fake_papers)}")

if __name__ == "__main__":
    main()
