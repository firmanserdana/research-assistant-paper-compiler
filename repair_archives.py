#!/usr/bin/env python3
"""
Repair archive papers by verifying DOIs and looking up correct DOIs
using Crossref bibliographic search (free, keyless) and Perplexity API (optional fallback).
Never destroys or wipes out historical archive files.
"""

import os
import re
import json
import time
import difflib
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from src.monitor import LiteratureMonitor

ARCHIVE_DIR = "src/archive"
REPORT_FILE = "repair_report.json"
CACHE_FILE = "doi_verification_cache.json"
USER_AGENT = "LiteratureMonitor/1.0 (mailto:contact@example.com)"

PPLX_API_KEY = os.getenv("PPLX_API_KEY")
if not PPLX_API_KEY and Path('.env').exists():
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('PPLX_API_KEY='):
                    PPLX_API_KEY = line.strip().split('=', 1)[1].strip().strip("'\"")
                    break
    except Exception:
        pass


def clean_title(t):
    if not t:
        return ""
    t = t.strip().strip('*').strip()
    t = re.sub(r'\[\d+\]', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def compute_title_similarity(t1, t2):
    c1 = re.sub(r'[^a-z0-9 ]', '', clean_title(t1).lower())
    c2 = re.sub(r'[^a-z0-9 ]', '', clean_title(t2).lower())
    if not c1 or not c2:
        return 0.0
    if c1 in c2 or c2 in c1:
        return 1.0
    w1 = set(c1.split())
    w2 = set(c2.split())
    if not w1 or not w2:
        return 0.0
    jaccard = len(w1 & w2) / len(w1 | w2)
    seq = difflib.SequenceMatcher(None, c1, c2).ratio()
    return max(jaccard, seq)


def verify_doi(doi, paper_title=None):
    """Verify a DOI against CrossRef API, optionally validating title similarity."""
    if not doi:
        return ("INVALID", None)

    if any(prefix in doi for prefix in ['10.48550/', '10.1101/', '10.31219/', 'arXiv']):
        return ("PREPRINT", None)

    if not doi.startswith('10.'):
        return ("INVALID", None)

    try:
        url = f"https://api.crossref.org/works/{doi}"
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                msg = data.get('message', {})
                title = (msg.get('title') or [''])[0]
                if paper_title:
                    sim = compute_title_similarity(paper_title, title)
                    if sim < 0.40:
                        return ("MISMATCH", title)
                return ("VERIFIED", title)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("FAKE", None)
        return ("ERROR", None)
    except Exception:
        return ("ERROR", None)

    return ("ERROR", None)


def find_doi_crossref(title, authors=""):
    """Search Crossref for the correct DOI based on paper title and authors."""
    if not title or len(title) < 8:
        return None

    try:
        query_str = title
        if authors and authors != 'Unknown':
            first_author = authors.split(';')[0].split(',')[0].strip()
            query_str = f"{title} {first_author}"

        encoded_query = urllib.parse.quote(query_str)
        url = f"https://api.crossref.org/works?query.bibliographic={encoded_query}&rows=2"
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                items = data.get('message', {}).get('items', [])
                for item in items:
                    candidate_doi = item.get('DOI', '').strip()
                    candidate_title = (item.get('title') or [''])[0].strip()

                    # Check title similarity
                    ratio = difflib.SequenceMatcher(
                        None, title.lower(), candidate_title.lower()
                    ).ratio()

                    if ratio > 0.65 and candidate_doi:
                        return candidate_doi
    except Exception as e:
        logger_debug = str(e)

    return None


def find_doi_perplexity(title, authors=""):
    """Fallback search using Perplexity API if configured."""
    if not PPLX_API_KEY:
        return None

    try:
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {PPLX_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a research assistant. Output ONLY the exact DOI (e.g. 10.xxxx/yyyy) for the paper, or 'NOT FOUND'. No markdown or extra text."
                },
                {
                    "role": "user",
                    "content": f"Find the DOI for: \"{title}\" by {authors}"
                }
            ],
            "temperature": 0.1,
            "max_tokens": 60
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            res = json.loads(response.read().decode('utf-8'))
            doi_candidate = res['choices'][0]['message']['content'].strip()
            doi_candidate = re.sub(r'^(?:DOI:\s*|doi:\s*)', '', doi_candidate).strip()
            match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', doi_candidate)
            if match:
                return match.group(0)
    except Exception:
        pass

    return None


def main():
    print("=" * 60)
    print("ARCHIVE DOI REPAIR UTILITY")
    print("=" * 60)

    monitor = LiteratureMonitor(provider="crossref")
    archive_path = Path(ARCHIVE_DIR)
    archive_files = sorted(archive_path.glob("papers_*.md"))

    results = {
        'total': 0,
        'verified': 0,
        'repaired_crossref': 0,
        'repaired_pplx': 0,
        'unrepaired': 0
    }

    for filepath in archive_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            papers = monitor._parse_archive_markdown(content)
        except Exception as e:
            print(f"Error parsing {filepath.name}: {e}")
            continue

        if not papers:
            continue

        file_changed = False

        for paper in papers:
            results['total'] += 1
            doi = monitor._normalize_doi(paper.get('doi', ''))
            paper['doi'] = doi

            status, _ = verify_doi(doi, paper_title=paper['title'])
            if status in ("VERIFIED", "PREPRINT"):
                results['verified'] += 1
                continue

            # Attempt repair via Crossref
            print(f"Repairing [{filepath.name}]: {paper['title'][:40]}... (old: {doi})")
            time.sleep(0.2)
            new_doi = find_doi_crossref(paper['title'], '; '.join(paper.get('authors', [])))

            if new_doi:
                v_status, _ = verify_doi(new_doi, paper_title=paper['title'])
                if v_status in ("VERIFIED", "PREPRINT"):
                    print(f"  ✓ Crossref Repaired: {new_doi}")
                    paper['doi'] = new_doi
                    results['repaired_crossref'] += 1
                    file_changed = True
                    continue

            # Attempt repair via Perplexity if configured
            if PPLX_API_KEY:
                time.sleep(0.2)
                pplx_doi = find_doi_perplexity(paper['title'], '; '.join(paper.get('authors', [])))
                if pplx_doi:
                    v_status, _ = verify_doi(pplx_doi, paper_title=paper['title'])
                    if v_status in ("VERIFIED", "PREPRINT"):
                        print(f"  ✓ Perplexity Repaired: {pplx_doi}")
                        paper['doi'] = pplx_doi
                        results['repaired_pplx'] += 1
                        file_changed = True
                        continue

            print(f"  - Unresolved DOI for: {paper['title'][:40]}")
            results['unrepaired'] += 1

        # Re-save file if any DOIs were repaired
        if file_changed:
            date_part = filepath.stem.replace('papers_', '')
            categories = {}
            for p in papers:
                cat = monitor._categorize(p)
                categories.setdefault(cat, []).append(p)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# Research Papers Compilation - {date_part}\n\n")
                f.write("## Summary\n")
                f.write(f"This compilation contains {len(papers)} papers in biorobotics research.\n\n")

                for cat, plist in categories.items():
                    f.write(f"## {cat} ({len(plist)} papers)\n\n")
                    for p in plist:
                        f.write(f"### {p['title']}\n")
                        f.write(f"**Authors:** {'; '.join(p.get('authors', []))}\n")
                        f.write(f"**DOI:** {p.get('doi', '')}\n")
                        f.write(f"**TRL:** {p.get('trl', 1)}\n")
                        f.write(f"**Keywords:** {', '.join(p.get('keywords', []))}\n")
                        f.write(f"**Summary:** {p.get('summary', '')}\n")
                        f.write("---\n\n")

            print(f"  Updated {filepath.name} with repaired DOIs.")

    print("\n" + "=" * 60)
    print("REPAIR SUMMARY")
    print("=" * 60)
    print(f"Total Papers Processed:    {results['total']}")
    print(f"Already Verified:          {results['verified']}")
    print(f"Repaired via Crossref:     {results['repaired_crossref']}")
    print(f"Repaired via Perplexity:   {results['repaired_pplx']}")
    print(f"Unrepaired (retained):     {results['unrepaired']}")

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    return 0


if __name__ == "__main__":
    main()
