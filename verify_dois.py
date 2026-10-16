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

import difflib
import re

ARCHIVE_DIR = "src/archive"
REPORT_FILE = "doi_verification_report.json"
CACHE_FILE = "doi_verification_cache.json"
USER_AGENT = "LiteratureMonitor/1.0 (mailto:contact@example.com)"


def clean_title(t):
    """Normalize paper title for fuzzy comparison."""
    if not t:
        return ""
    t = t.strip().strip('*').strip()
    t = re.sub(r'\[\d+\]', '', t)  # strip citation brackets like [1]
    return re.sub(r'\s+', ' ', t).strip()


def compute_title_similarity(t1, t2):
    """
    Compute title similarity score between claimed title and CrossRef title.
    Returns a float between 0.0 and 1.0.
    """
    c1 = re.sub(r'[^a-z0-9 ]', '', clean_title(t1).lower())
    c2 = re.sub(r'[^a-z0-9 ]', '', clean_title(t2).lower())
    if not c1 or not c2:
        return 0.0
    # Substring match (e.g. main title without subtitle) only if length ratio >= 0.50
    if (c1 in c2 or c2 in c1) and (min(len(c1), len(c2)) / max(len(c1), len(c2)) >= 0.50):
        return 1.0
    w1 = set(c1.split())
    w2 = set(c2.split())
    if not w1 or not w2:
        return 0.0
    jaccard = len(w1 & w2) / len(w1 | w2)
    seq = difflib.SequenceMatcher(None, c1, c2).ratio()
    return max(jaccard, seq)


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

    # Preprints: must still resolve (Crossref, or DataCite for arXiv)
    if any(prefix in doi for prefix in ['10.48550/', '10.1101/', '10.31219/', 'arXiv']):
        for url in (f"https://api.crossref.org/works/{doi}",
                    f"https://api.datacite.org/dois/{doi}"):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
                with urllib.request.urlopen(req, timeout=12) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    if 'message' in data:
                        msg = data['message']
                        real_title = (msg.get('title') or [''])[0]
                        sub = (msg.get('subtitle') or [''])[0]
                        if sub and sub.lower() not in real_title.lower():
                            real_title = f"{real_title}: {sub}"
                    else:
                        real_title = data['data']['attributes']['titles'][0]['title']
                    return ("PREPRINT", {'real_title': re.sub(r'\s+', ' ', real_title).strip()})
            except Exception:
                continue
        return ("FAKE", "Preprint DOI not found in Crossref or DataCite")

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
                sub = (message.get('subtitle') or [''])[0]
                if sub and sub.lower() not in real_title.lower():
                    real_title = f"{real_title}: {sub}"
                real_authors = message.get('author', [])
                author_names = [
                    f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in real_authors[:3]
                ]
                return ("VERIFIED", {
                    'real_title': re.sub(r'\s+', ' ', real_title).strip(),
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
            p_status = status
            p_details = details
            if status in ("VERIFIED", "PREPRINT") and isinstance(details, dict):
                real_title = details.get('real_title', '')
                claimed_title = p.get('title', '')
                sim = compute_title_similarity(claimed_title, real_title)
                p['title_similarity'] = round(sim, 3)
                if sim < 0.70:
                    p_status = "FAKE"
                    p_details = {
                        'error': f"Title mismatch with CrossRef record (similarity: {sim:.2f})",
                        'claimed_title': claimed_title,
                        'real_title': real_title,
                        'similarity': round(sim, 3)
                    }
                    print(f"  [MISMATCH] {claimed_title[:30]} != {real_title[:30]} (sim: {sim:.2f})")
            p['verification_status'] = p_status
            p['verification_details'] = p_details
            results.setdefault(p_status, []).append(p)

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
    print(f"  Fake/Mismatch: {fake_count}")
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
    return 1 if (fake_count > 0 or invalid_count > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
