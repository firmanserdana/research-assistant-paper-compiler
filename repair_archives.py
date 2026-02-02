#!/usr/bin/env python3
"""
Repair archive papers by verifying DOIs and using Perplexity to find correct ones.
Uses standard library only (no external dependencies like openai/requests).
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

ARCHIVE_DIR = "src/archive"
REPORT_FILE = "repair_report.json"

# Perplexity API Config
PPLX_API_KEY = os.getenv("PPLX_API_KEY")

# Manually read .env if key not in env
if not PPLX_API_KEY:
    env_path = Path('.env')
    if env_path.exists():
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    if line.strip().startswith('PPLX_API_KEY='):
                        PPLX_API_KEY = line.strip().split('=', 1)[1].strip().strip("'").strip('"')
                        print("Loaded PPLX_API_KEY from .env")
                        break
        except Exception as e:
            print(f"Failed to read .env: {e}")

PPLX_BASE_URL = "https://api.perplexity.ai/chat/completions"

def call_perplexity(prompt):
    """Call Perplexity API using urllib."""
    if not PPLX_API_KEY:
        return None
        
    headers = {
        "Authorization": f"Bearer {PPLX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": "You are a helpful research assistant. You only output the DOI and nothing else. No markdown, no text."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    
    try:
        req = urllib.request.Request(
            PPLX_BASE_URL, 
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"  Perplexity API error: {e}")
        return None

def parse_archive_file(filepath):
    """Parse papers from a markdown archive file."""
    papers = []
    current_paper = None
    current_category = "Unknown"
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        # Detect category headers
        if line.startswith('## ') and not line.startswith('## Summary'):
            if '(' in line and 'papers)' in line:
                current_category = line[3:].split(' (')[0].strip()
            else:
                current_category = line[3:].strip()
            
        # Start of a new paper
        elif line.startswith('### '):
            if current_paper and current_paper.get('doi'):
                papers.append(current_paper)
            current_paper = {
                'title': line[4:].strip(), 
                'category': current_category,
                'source_file': os.path.basename(filepath),
                'authors': '',
                'doi': '',
                'trl': '',
                'keywords': '',
                'summary': ''
            }
            
        # Collect metadata
        if current_paper:
            if line.startswith('**Authors:**'):
                current_paper['authors'] = line[12:].strip()
            elif line.startswith('**DOI:**'):
                doi = line[8:].strip()
                # Clean up the DOI
                doi = re.sub(r'\[?\d+\]?$', '', doi).strip()
                prefixes = ['https://doi.org/', 'http://doi.org/', 'doi.org/', 'DOI: ', 'doi:']
                for prefix in prefixes:
                    if doi.lower().startswith(prefix.lower()):
                        doi = doi[len(prefix):]
                current_paper['doi'] = doi.strip()
            elif line.startswith('**TRL:**'):
                current_paper['trl'] = line[8:].strip()
            elif line.startswith('**Keywords:**'):
                current_paper['keywords'] = line[13:].strip()
            elif line.startswith('**Summary:**'):
                current_paper['summary'] = line[12:].strip()
            elif line and not line.startswith('**') and not line.startswith('###'):
                # Append to summary if it's a continuation
                if current_paper.get('summary'):
                    current_paper['summary'] += " " + line
    
    # Add the last paper
    if current_paper and current_paper.get('doi'):
        papers.append(current_paper)
        
    return papers

def verify_doi(doi):
    """Verify a DOI against CrossRef API. Returns (status, details)."""
    if not doi:
        return ("INVALID", "Empty DOI")
    
    # Skip preprints
    if any(prefix in doi for prefix in ['10.48550/', '10.1101/', 'arXiv']):
        return ("PREPRINT", "Preprint - not verified")
    
    try:
        url = f"https://api.crossref.org/works/{doi}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'DOIVerifier/1.0 (mailto:contact@example.com)'
        })
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                real_title = data.get('message', {}).get('title', [''])[0]
                real_authors_list = data.get('message', {}).get('author', [])
                author_names = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in real_authors_list[:3]]
                return ("VERIFIED", {
                    'real_title': real_title,
                    'real_authors': ", ".join(author_names)
                })
                
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("FAKE", "DOI not found in CrossRef")
    except Exception as e:
        return ("ERROR", str(e))
    
    return ("ERROR", "Unknown error")

def find_correct_doi(paper):
    """Use Perplexity to find the correct DOI."""
    if not PPLX_API_KEY:
        return None

    print(f"  Attempting repair for: {paper['title']}")
    
    prompt = (
        f"Find the correct DOI for the research paper titled: \"{paper['title']}\" "
        f"by authors: \"{paper['authors']}\". "
        "Return ONLY the DOI string (e.g., 10.xxxx/yyyy) or a JSON object with correct info. "
        "If you cannot find the exact paper, return 'NOT FOUND'."
    )
    
    result = call_perplexity(prompt)
    
    if not result:
        return None
        
    # Clean up result
    result = result.replace('DOI:', '').replace('doi:', '').strip()
    if result.endswith('.'):
            result = result[:-1]

    if "NOT FOUND" in result or len(result) < 5 or " " in result:
        print(f"  Result: Not found ({result})")
        return None
        
    print(f"  Result: {result}")
    return result

def main():
    print("=" * 60)
    print("ARCHIVE REPAIR STARTED")
    if not PPLX_API_KEY:
        print("WARNING: PPLX_API_KEY not found. Repair functionality disabled.")
    print("=" * 60)
    
    archive_path = Path(ARCHIVE_DIR)
    archive_files = sorted(archive_path.glob("papers_*.md"))
    
    results = {
        'total': 0,
        'verified_initial': 0,
        'repaired': 0,
        'failed_repair': 0,
        'preprints': 0
    }
    
    for filepath in archive_files:
        print(f"\nProcessing {filepath.name}...")
        try:
            papers = parse_archive_file(filepath)
        except Exception as e:
            print(f"Error parsing {filepath.name}: {e}")
            continue

        valid_papers = []
        
        for paper in papers:
            results['total'] += 1
            doi = paper.get('doi', '')
            status, details = verify_doi(doi)
            
            if status == "VERIFIED":
                results['verified_initial'] += 1
                valid_papers.append(paper)
            elif status == "PREPRINT":
                results['preprints'] += 1
                valid_papers.append(paper)
            elif status in ["FAKE", "INVALID"]:
                # Attempt repair
                new_doi = find_correct_doi(paper)
                if new_doi:
                    # Verify the new DOI
                    new_status, new_details = verify_doi(new_doi)
                    if new_status == "VERIFIED":
                        print(f"  ✓ REPAIRED! {doi} -> {new_doi}")
                        paper['doi'] = new_doi
                        # Update title/authors if provided by CrossRef to match reality
                        if isinstance(new_details, dict):
                            if new_details.get('real_title'):
                                paper['title'] = new_details['real_title']
                            if new_details.get('real_authors'):
                                paper['authors'] = new_details['real_authors']
                        
                        results['repaired'] += 1
                        valid_papers.append(paper)
                    else:
                        print(f"  ✗ Repair failed (invalid new DOI): {new_doi}")
                        results['failed_repair'] += 1
                else:
                    results['failed_repair'] += 1
            else:
                print(f"  Skipping error/unknown status: {status}")
                results['failed_repair'] += 1

        # Reconstruct file content
        if valid_papers:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# Biorobotics and Artificial Intelligence Papers\n")
                f.write(f"Generated on {filepath.stem.replace('papers_', '')}\n\n")
                
                # Group by category
                by_category = {}
                for p in valid_papers:
                    cat = p['category']
                    if cat not in by_category:
                        by_category[cat] = []
                    by_category[cat].append(p)
                
                f.write(f"## Summary\nTotal Papers: {len(valid_papers)}\n\n")
                
                for cat, plist in by_category.items():
                    f.write(f"## {cat} ({len(plist)} papers)\n\n")
                    for p in plist:
                        f.write(f"### {p['title']}\n")
                        f.write(f"**Authors:** {p['authors']}\n")
                        f.write(f"**DOI:** {p['doi']}\n")
                        f.write(f"**TRL:** {p['trl']}\n")
                        f.write(f"**Keywords:** {p['keywords']}\n")
                        f.write(f"**Summary:** {p['summary']}\n\n")
            print(f"  Rewrote {filepath.name} with {len(valid_papers)} papers")
        else:
            print(f"  {filepath.name} has NO valid papers. Adding placeholder.")
            with open(filepath, 'w', encoding='utf-8') as f:
                 f.write(f"# Biorobotics and Artificial Intelligence Papers\n")
                 f.write(f"Generated on {filepath.stem.replace('papers_', '')}\n\n")
                 f.write("## Summary\nNo verified papers found in this archive.\n")

    print("\n" + "=" * 60)
    print("REPAIR SUMMARY")
    print("=" * 60)
    print(f"Total Papers Processed: {results['total']}")
    print(f"Initially Verified:     {results['verified_initial']}")
    print(f"Repaired:               {results['repaired']}")
    print(f"Preprints:              {results['preprints']}")
    print(f"Still Fake/removed:     {results['failed_repair']}")

if __name__ == "__main__":
    main()

