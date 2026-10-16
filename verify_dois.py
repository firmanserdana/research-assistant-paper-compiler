#!/usr/bin/env python3
"""
Fact-check all papers in the archive directory by verifying DOIs against CrossRef API.
Maintains a local cache to avoid redundant network calls on repeated runs.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from src.monitor import LiteratureMonitor

ARCHIVE_DIR = "src/archive"
REPORT_FILE = "doi_verification_report.json"
CACHE_FILE = "doi_verification_cache.json"
USER_AGENT = "LiteratureMonitor/1.0 (mailto:contact@example.com)"


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: could not load cache: {e}")
    return {}


def save_cache(cache):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save cache: {e}")


def verify_single_doi(doi):
    """
    Verify a DOI against CrossRef API.
    Returns (status, details).
    """
    if not doi:
        return ("INVALID", "Empty or missing DOI")

    # Skip preprints
    if any(prefix in doi for prefix in ['10.48550/', '10.1101/', '10.31219/', 'arXiv']):
        return ("PREPRINT", "Preprint - accepted without remote lookup")

    if not doi.startswith('10.'):
        return ("INVALID", "Does not follow standard DOI 10.xxxx prefix")

    try:
        url = f"https://api.crossref.org/works/{doi}"
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})

        with urllib.request.urlopen(req, timeout=12) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                message = data.get('message', {})
                real_title = (message.get('title') or [''])[0]
                real_authors = message.get('author', [])
                author_names = [
                    f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in real_authors[:3]
                ]
                return ("VERIFIED", {
                    'real_title': real_title[:120],
                    'real_authors': author_names
                })
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("FAKE", "DOI not found in CrossRef")
        return ("ERROR", f"HTTP {e.code}")
    except urllib.error.URLError as e:
        return ("ERROR", str(e.reason))
    except Exception as e:
        return ("ERROR", str(e))

    return ("ERROR", "Unknown response state")


def main():
    print("=" * 60)
    print("DOI VERIFICATION - ARCHIVE PAPERS")
    print("=" * 60)

    monitor = LiteratureMonitor(provider="crossref")
    archive_path = Path(ARCHIVE_DIR)
    archive_files = sorted(archive_path.glob("papers_*.md"))
    print(f"Found {len(archive_files)} archive files")

    all_papers = []
    for filepath in archive_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            papers = monitor._parse_archive_markdown(content)
            for p in papers:
                p['source_file'] = filepath.name
            all_papers.extend(papers)
        except Exception as e:
            print(f"Error reading {filepath.name}: {e}")

    print(f"Total papers to verify: {len(all_papers)}")
    print("-" * 60)

    cache = load_cache()
    cached_hits = 0

    results = {
        'VERIFIED': [],
        'FAKE': [],
        'PREPRINT': [],
        'ERROR': [],
        'INVALID': []
    }

    # Group papers by normalized DOI to minimize network requests
    unique_dois = {}
    for p in all_papers:
        doi = monitor._normalize_doi(p.get('doi', ''))
        p['normalized_doi'] = doi
        unique_dois.setdefault(doi, []).append(p)

    print(f"Unique DOIs to verify: {len(unique_dois)}")

    for i, (doi, papers_group) in enumerate(unique_dois.items()):
        short_title = papers_group[0].get('title', '')[:35]
        print(f"[{i+1}/{len(unique_dois)}] {doi or 'EMPTY'[:20]} ({short_title})...", end=" ", flush=True)

        if doi in cache:
            cached_hits += 1
            status, details = cache[doi]['status'], cache[doi]['details']
            print(f"cached ({status})")
        else:
            status, details = verify_single_doi(doi)
            cache[doi] = {'status': status, 'details': details, 'checked_at': time.time()}
            if status == "VERIFIED":
                print("✓")
            elif status == "PREPRINT":
                print("~ preprint")
            elif status == "FAKE":
                print("✗ FAKE")
            else:
                print(f"? {status}")
            time.sleep(0.2)  # Polite rate limiting

        for p in papers_group:
            p['verification_status'] = status
            p['verification_details'] = details
            results.setdefault(status, []).append(p)

    save_cache(cache)

    # Print summary
    verified_count = len(results.get('VERIFIED', []))
    fake_count = len(results.get('FAKE', []))
    preprint_count = len(results.get('PREPRINT', []))
    error_count = len(results.get('ERROR', []))
    invalid_count = len(results.get('INVALID', []))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Verified:      {verified_count}")
    print(f"  Preprints:     {preprint_count}")
    print(f"  Fake:          {fake_count}")
    print(f"  Invalid/Empty: {invalid_count}")
    print(f"  Errors:        {error_count}")
    print(f"  Cache hits:    {cached_hits}")

    report = {
        'summary': {
            'total': len(all_papers),
            'unique_dois': len(unique_dois),
            'verified': verified_count,
            'preprints': preprint_count,
            'fake': fake_count,
            'invalid': invalid_count,
            'errors': error_count,
            'cache_hits': cached_hits
        },
        'verified_papers': results.get('VERIFIED', []),
        'preprints': results.get('PREPRINT', []),
        'fake_papers': results.get('FAKE', []),
        'invalid_papers': results.get('INVALID', []),
        'errors': results.get('ERROR', [])
    }

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    print(f"\nDetailed report saved to: {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
