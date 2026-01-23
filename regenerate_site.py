#!/usr/bin/env python3
"""
Regenerate the GitHub Pages site using only verified papers from archives.
This script can be run standalone to refresh the docs/ folder.
"""

import os
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

def parse_verified_papers():
    """Parse only verified papers from cleaned archive files."""
    papers = []
    archive_dir = 'src/archive'
    
    if not os.path.exists(archive_dir):
        return papers
    
    for filename in sorted(os.listdir(archive_dir)):
        if not filename.endswith('.md'):
            continue
            
        filepath = os.path.join(archive_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Only parse files with verified papers section
        if '## Verified Papers' not in content:
            continue
        
        # Extract verified papers section
        in_verified = False
        current_paper = None
        
        for line in content.split('\n'):
            if line.startswith('## Verified Papers'):
                in_verified = True
                continue
            if in_verified and line.startswith('## '):
                # End of verified section
                break
            
            if in_verified:
                if line.startswith('### '):
                    if current_paper and current_paper.get('title'):
                        papers.append(current_paper)
                    current_paper = {'title': line[4:].strip()}
                elif current_paper:
                    if line.startswith('**Authors:**'):
                        current_paper['authors'] = line[12:].strip()
                    elif line.startswith('**DOI:**'):
                        current_paper['doi'] = line[8:].strip()
                    elif line.startswith('**Verified Title:**'):
                        # Use the real verified title
                        current_paper['title'] = line[19:].strip()
                    elif line.startswith('**Verified Authors:**'):
                        current_paper['authors'] = line[21:].strip()
        
        # Add last paper
        if current_paper and current_paper.get('title'):
            papers.append(current_paper)
    
    # Add default fields for template
    for paper in papers:
        if 'trl' not in paper:
            paper['trl'] = 'N/A'
        if 'keywords' not in paper:
            paper['keywords'] = ['verified paper']
        if 'summary' not in paper:
            paper['summary'] = 'DOI verified against CrossRef.'
    
    return papers

def main():
    print("Regenerating GitHub Pages site with verified papers only...")
    
    # Create docs directory
    os.makedirs('docs', exist_ok=True)
    
    # Parse verified papers
    papers = parse_verified_papers()
    print(f"Found {len(papers)} verified papers")
    
    # Setup Jinja2
    env = Environment(loader=FileSystemLoader('src/templates'))
    template = env.get_template('index.html')
    
    # Render template
    html = template.render(
        papers=papers,
        updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        count=len(papers),
        total=len(papers)
    )
    
    # Write output
    with open('docs/index.html', 'w') as f:
        f.write(html)
    
    print(f"Generated docs/index.html with {len(papers)} verified papers")
    print("Site regeneration complete!")

if __name__ == "__main__":
    main()
