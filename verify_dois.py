#!/usr/bin/env python3
"""
Fact-check all papers in archive directory by verifying DOIs against CrossRef API.
Uses only standard library (urllib) - no external dependencies.
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

ARCHIVE_DIR = "src/archive"
REPORT_FILE = "doi_verification_report.json"

def parse_archive_file(filepath):
    """Parse papers from a markdown archive file."""
    papers = []
    current_paper = None
    current_category = "Unknown"
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Skip files that have already been cleaned (contain removal logs)
    if "Papers Removed" in content:
        return []
    
    for line in content.split('\n'):
        # Detect category headers
        if line.startswith('## ') and '(' in line and 'papers)' in line:
            current_category = line[3:].split(' (')[0].strip()
        elif line.startswith('## ') and not line.startswith('## Summary'):
            current_category = line[3:].strip()
            
        # Start of a new paper
        elif line.startswith('### '):
            if current_paper and current_paper.get('doi'):
                papers.append(current_paper)
            current_paper = {
                'title': line[4:].strip(), 
                'category': current_category,
                'source_file': os.path.basename(filepath)
            }
            
        # Paper metadata
        elif current_paper and line.startswith('**Authors:**'):
            current_paper['authors'] = line[12:].strip()
        elif current_paper and line.startswith('**DOI:**'):
            doi = line[8:].strip()
            # Clean up the DOI
            doi = re.sub(r'\[?\d+\]?$', '', doi).strip()
            prefixes = ['https://doi.org/', 'http://doi.org/', 'doi.org/', 'DOI: ', 'doi:']
            for prefix in prefixes:
                if doi.lower().startswith(prefix.lower()):
                    doi = doi[len(prefix):]
            current_paper['doi'] = doi.strip()
    
    # Add the last paper
    if current_paper and current_paper.get('doi'):
        papers.append(current_paper)
        
    return papers

def verify_doi(doi):
    """Verify a DOI against CrossRef API. Returns (doi, status, details)."""
    if not doi:
        return (doi, "INVALID", "Empty DOI")
    
    # Skip preprints
    if any(prefix in doi for prefix in ['10.48550/', '10.1101/', 'arXiv']):
        return (doi, "PREPRINT", "Preprint - not verified")
    
    try:
        url = f"https://api.crossref.org/works/{doi}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'DOIVerifier/1.0 (mailto:contact@example.com)'
        })
        
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                real_title = data.get('message', {}).get('title', [''])[0]
                real_authors = data.get('message', {}).get('author', [])
                author_names = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in real_authors[:3]]
                return (doi, "VERIFIED", {
                    'real_title': real_title[:100],
                    'real_authors': author_names
                })
                
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return (doi, "FAKE", "DOI not found in CrossRef")
        return (doi, "ERROR", f"HTTP {e.code}")
    except urllib.error.URLError as e:
        return (doi, "ERROR", str(e.reason))
    except Exception as e:
        return (doi, "ERROR", str(e))
    
    return (doi, "ERROR", "Unknown error")

def main():
    print("=" * 60)
    print("DOI VERIFICATION - ALL ARCHIVE PAPERS")
    print("=" * 60)
    
    # Find all archive files
    archive_path = Path(ARCHIVE_DIR)
    archive_files = sorted(archive_path.glob("papers_*.md"))
    print(f"\nFound {len(archive_files)} archive files")
    
    # Parse all papers
    all_papers = []
    for filepath in archive_files:
        papers = parse_archive_file(filepath)
        all_papers.extend(papers)
        if papers:
            print(f"  {filepath.name}: {len(papers)} papers")
    
    print(f"\nTotal papers to verify: {len(all_papers)}")
    print("-" * 60)
    
    # Verify DOIs with rate limiting
    results = {
        'VERIFIED': [],
        'FAKE': [],
        'PREPRINT': [],
        'ERROR': [],
        'INVALID': []
    }
    
    for i, paper in enumerate(all_papers):
        doi = paper.get('doi', '')
        title_short = paper.get('title', '')[:40]
        print(f"[{i+1}/{len(all_papers)}] {title_short}...", end=" ", flush=True)
        
        doi, status, details = verify_doi(doi)
        paper['verification_status'] = status
        paper['verification_details'] = details
        
        if status not in results:
            results[status] = []
        results[status].append(paper)
        
        if status == "VERIFIED":
            print("✓")
        elif status == "FAKE":
            print("✗ FAKE")
        elif status == "PREPRINT":
            print("~ preprint")
        else:
            print(f"? {status}")
        
        # Rate limiting - be nice to CrossRef
        time.sleep(0.3)
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    verified_count = len(results.get('VERIFIED', []))
    fake_count = len(results.get('FAKE', []))
    preprint_count = len(results.get('PREPRINT', []))
    error_count = len(results.get('ERROR', []))
    
    print(f"  Verified:  {verified_count}")
    print(f"  FAKE:      {fake_count}")
    print(f"  Preprints: {preprint_count}")
    print(f"  Errors:    {error_count}")
    
    # Save detailed report
    report = {
        'summary': {
            'total': len(all_papers),
            'verified': verified_count,
            'fake': fake_count,
            'preprints': preprint_count,
            'errors': error_count
        },
        'fake_papers': results.get('FAKE', []),
        'verified_papers': results.get('VERIFIED', []),
        'preprints': results.get('PREPRINT', []),
        'errors': results.get('ERROR', [])
    }
    
    with open(REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nDetailed report saved to: {REPORT_FILE}")
    
    # List fake papers grouped by file
    if results.get('FAKE'):
        print("\n" + "=" * 60)
        print("FAKE PAPERS DETECTED")
        print("=" * 60)
        
        # Group by source file
        by_file = {}
        for paper in results['FAKE']:
            src = paper['source_file']
            if src not in by_file:
                by_file[src] = []
            by_file[src].append(paper)
        
        for src_file, papers in sorted(by_file.items()):
            print(f"\n{src_file} ({len(papers)} fake):")
            for paper in papers:
                print(f"  - {paper['title'][:50]}...")
                print(f"    DOI: {paper['doi']}")
    
    return results

if __name__ == "__main__":
    main()
