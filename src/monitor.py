import os
import re
import json
import logging
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from pyzotero import zotero
from jinja2 import Environment, FileSystemLoader

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('literature_monitor')

class LiteratureMonitor:
    """Monitor biorobotics literature and add new papers to Zotero library."""
    
    def __init__(self, model="gemini-2.5-pro", provider="gemini"):
        """
        Initialize the literature monitor.
        
        Args:
            model (str): The AI model to use
            provider (str): AI provider - "perplexity", "anthropic", or "ollama"
        """
        # Check required environment variables
        required_vars = ["ZOTERO_USER_ID", "ZOTERO_API_KEY"]
        if provider == "perplexity":
            required_vars.append("PPLX_API_KEY")
        elif provider == "anthropic":
            required_vars.append("ANTHROPIC_API_KEY")
        elif provider == "gemini":
            required_vars.append("GEMINI_API_KEY")
            
        self._check_environment(required_vars)
        
        self.client = self._get_client(provider)
        self.model = model
        
        try:
            self.zot = zotero.Zotero(
                os.getenv("ZOTERO_USER_ID"),
                'user',
                os.getenv("ZOTERO_API_KEY")
            )
            # Test connection
            self.zot.collections()
        except Exception as e:
            logger.error(f"Failed to connect to Zotero: {str(e)}")
            raise
        
        # Read search terms from search_terms.txt
        with open('search_terms.txt', 'r') as f:
            self.search_terms = [line.strip() for line in f if line.strip()]

        # Setup template engine
        self.template_env = Environment(
            loader=FileSystemLoader('src/templates')
        )

    def _check_environment(self, required_vars):
        """Check if all required environment variables are set."""
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            error_msg = f"Missing environment variables: {', '.join(missing)}"
            logger.error(error_msg)
            raise EnvironmentError(error_msg)

    def _get_client(self, provider):
        """
        Get the appropriate API client based on the provider.
        
        Args:
            provider (str): The AI provider to use
            
        Returns:
            The initialized client
        """
        try:
            if provider == "anthropic":
                from anthropic import Anthropic
                return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            elif provider == "ollama":
                return OpenAI(base_url="http://localhost:11434/v1")
            elif provider == "gemini":
                return OpenAI(
                    api_key=os.getenv("GEMINI_API_KEY"),
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                )
            else:
                return OpenAI(
                    api_key=os.getenv("PPLX_API_KEY"),
                    base_url="https://api.perplexity.ai"
                )
        except Exception as e:
            logger.error(f"Failed to initialize {provider} client: {str(e)}")
            raise
    
    def load_papers_from_archives(self):
        """
        Load papers from all archive Markdown files.
        
        Returns:
            list: All historical papers found in archive files
        """
        all_papers = []
        archive_dir = 'src/archive'
        
        if not os.path.exists(archive_dir):
            return all_papers
            
        # Find all markdown files in the archive directory
        archive_files = [f for f in os.listdir(archive_dir) if f.endswith('.md')]
        
        for filename in archive_files:
            try:
                filepath = os.path.join(archive_dir, filename)
                with open(filepath, 'r') as f:
                    content = f.read()
                    
                # Parse papers from the markdown file
                papers = self._parse_archive_markdown(content)
                all_papers.extend(papers)
                
            except Exception as e:
                logger.error(f"Failed to load papers from {filename}: {str(e)}")
                
        return all_papers

    def _parse_archive_markdown(self, content):
        """
        Parse papers from an archive markdown file.
        
        Args:
            content (str): Markdown file content
            
        Returns:
            list: Extracted paper dictionaries
        """
        papers = []
        current_paper = None
        current_category = "General Biorobotics"
        
        for line in content.split('\n'):
            # Detect category headers
            if line.startswith('## ') and ' papers)' in line:
                current_category = line[3:].split(' (')[0].strip()
                
            # Start of a new paper
            elif line.startswith('### '):
                if current_paper:
                    papers.append(current_paper)
                current_paper = {'title': line[4:].strip(), 'category': current_category}
                
            # Paper metadata
            elif current_paper and line.startswith('**Authors:**'):
                current_paper['authors'] = line[12:].strip().split('; ')
            elif current_paper and line.startswith('**DOI:**'):
                current_paper['doi'] = self._normalize_doi(line[8:].strip())
            elif current_paper and line.startswith('**TRL:**'):
                try:
                    current_paper['trl'] = int(line[8:].strip())
                except ValueError:
                    current_paper['trl'] = 1
            elif current_paper and line.startswith('**Keywords:**'):
                current_paper['keywords'] = [k.strip() for k in line[13:].split(',')]
            elif current_paper and line.startswith('**Summary:**'):
                current_paper['summary'] = line[12:].strip()
        
        # Add the last paper if there is one
        if current_paper:
            papers.append(current_paper)
            
        return papers

    def _categorize(self, paper):
        """
        Categorize a paper based on its source search term.
        
        Args:
            paper (dict): Paper metadata
            
        Returns:
            str: Category name
        """
        # If we have a category from the source term, use that
        if 'category' in paper:
            return paper['category']
        
        # Fall back to the old method if needed
        text = f"{paper['title']} {' '.join(paper['keywords'])}".lower()
        
        # Check for specific categories
        if 'emg' in text:
            return 'EMG Decoding'
        elif 'intracortical' in text:
            return 'Intracortical Decoding'
        elif 'stimulation' in text:
            return 'Nerve Stimulation'
        
        # Default category
        return 'General Biorobotics'

    def _deep_research_query(self, term):
        """
        Query the AI provider for papers on a specific term.
        
        Args:
            term (str): The search term
            
        Returns:
            tuple: (search_term, AI-generated research results)
        """
        try:
            logger.info(f"Researching term: {term}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": f"""Provide recent peer-reviewed papers about {term} 
                    in biomedical engineering and robotics. Include DOI (without URL prefix), TRL (1-9), and technical 
                    keywords. Format:
                    Title: [Title]
                    Authors: [Author1; Author2; Author3]
                    DOI: [DOI number only, e.g., 10.1234/example]
                    TRL: [Number]
                    Keywords: [Keyword1, Keyword2]
                    
                    IMPORTANT: 
                    - Provide actual author names, not placeholders like "Not specified" or "See article"
                    - Provide only the DOI number (e.g., 10.1234/example), not the full URL
                    - Skip papers where author information is unavailable"""
                }],
                temperature=0.2,
                max_tokens=2000
            )
            # Return both the term and the response content
            return (term, response.choices[0].message.content)
        except Exception as e:
            logger.error(f"API request failed: {str(e)}")
            return (term, "")  # Return empty string to handle gracefully
            
    def _save_to_zotero(self, paper):
        """
        Save a paper to the Zotero library.
        
        Args:
            paper (dict): Paper metadata
        """
        try:
            # Parse authors more robustly
            creators = []
            for author in paper['authors']:
                parts = author.split()
                if len(parts) > 1:
                    creators.append({
                        'creatorType': 'author', 
                        'firstName': ' '.join(parts[:-1]), 
                        'lastName': parts[-1]
                    })
                else:
                    creators.append({
                        'creatorType': 'author',
                        'lastName': author,
                        'firstName': ''
                    })
            
            # Get or create collection
            category_name = self._categorize(paper)
            collection_id = self._get_or_create_collection(category_name)
            
            # Create item
            result = self.zot.create_items([{
                'itemType': 'journalArticle',
                'title': paper['title'],
                'creators': creators,
                'DOI': paper['doi'],
                'tags': [{'tag': k} for k in paper['keywords']],
                'collections': [collection_id] if collection_id else [],
                'extra': f"TRL: {paper['trl']} | Added: {datetime.now().isoformat()}"
            }])
            logger.info(f"Added paper to Zotero: {paper['title']}")
            return result
        except Exception as e:
            logger.error(f"Failed to save paper to Zotero: {str(e)}")
            return None

    def _get_or_create_collection(self, category_name):
        """
        Get or create a Zotero collection by name.
        
        Args:
            category_name (str): The name of the category/collection
            
        Returns:
            str: The collection ID
        """
        try:
            collections = self.zot.collections()
            
            # Look for existing collection
            for collection in collections:
                if collection['data']['name'] == category_name:
                    return collection['key']
            
            # Create new collection if not found
            result = self.zot.create_collections([{'name': category_name}])
            if result and 'successful' in result and result['successful']:
                return result['successful']['0']
            
            # Return None if we couldn't create or find collection
            return None
        except Exception as e:
            logger.error(f"Error with Zotero collection: {str(e)}")
            return None

    def _parse_response(self, content):
        papers = []
        current = {}
        
        for line in content.split('\n'):
            if line.startswith('Title:'):
                if current.get('title'):  # We've hit a new paper
                    papers.append(current)
                    current = {}
                current['title'] = line[6:].strip()
            elif line.startswith('Authors:'):
                current['authors'] = line[8:].strip().split('; ')
            elif line.startswith('DOI:'):
                current['doi'] = self._normalize_doi(line[4:].strip())
            elif line.startswith('TRL:'):
                # Extract the first number found or default to 5
                trl_text = line[4:].strip()
                try:
                    # Try direct conversion first
                    current['trl'] = int(trl_text)
                except ValueError:
                    # Look for any numbers in the string
                    numbers = re.findall(r'\d+', trl_text)
                    if numbers:
                        # Use the first number found
                        current['trl'] = int(numbers[0])
                    else:
                        # Default to 5 (middle of the TRL scale)
                        current['trl'] = 5
                        logger.warning(f"Could not parse TRL value '{trl_text}', defaulting to 5")
            elif line.startswith('Keywords:'):
                current['keywords'] = [k.strip() for k in line[9:].split(',')]
                
        # Add the last paper if not already added
        if current.get('title'):
            papers.append(current)
                
        return [p for p in papers if self._validate(p)]

    def _normalize_doi(self, doi):
        """
        Normalize a DOI by removing any URL prefix, reference numbers, and other artifacts.
        
        Args:
            doi (str): The DOI string which may include URL prefix, reference numbers, or other artifacts
            
        Returns:
            str: The normalized DOI without URL prefix, reference numbers, or artifacts
        """
        if not doi:
            return doi
        
        # Remove common URL prefixes
        doi = doi.strip()
        prefixes = ['https://doi.org/', 'http://doi.org/', 'doi.org/', 'DOI: ', 'doi:']
        for prefix in prefixes:
            if doi.startswith(prefix):
                doi = doi[len(prefix):]
            elif doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix):]
        
        # Remove reference numbers like [1], [2], [3], etc.
        doi = re.sub(r'\[\d+\]$', '', doi)
        
        # Remove parenthetical information at the end (e.g., journal names, dates)
        # Only if it's at the very end and in parentheses
        doi = re.sub(r'\s*\([^)]*\)\s*\[\d+\]$', '', doi)
        doi = re.sub(r'\s*\([^)]*\)$', '', doi)
        
        # Remove placeholder text if present
        if doi.startswith('[') and doi.endswith(']'):
            return ""  # Return empty string for placeholder DOIs like [Not provided in search results]
        
        return doi.strip()

    def _validate(self, paper):
        """
        Validate that a paper has all required fields and valid data.
        
        Args:
            paper (dict): Paper metadata
            
        Returns:
            bool: True if paper is valid
        """
        # Check DOI validity
        doi = paper.get('doi', '')
        if not doi or '[' in doi or 'not provided' in doi.lower() or 'not available' in doi.lower():
            logger.warning(f"Rejecting paper with invalid DOI: {paper.get('title', 'Unknown')}")
            return False
        
        # Check basic requirements
        if not all([
            paper.get('title'),
            len(paper.get('authors', [])) > 0,
            1 <= paper.get('trl', 0) <= 9
        ]):
            return False
        
        # Filter out invalid author entries
        authors = paper.get('authors', [])
        for author in authors:
            author_lower = author.lower()
            # Check for placeholder text that indicates missing author information
            if any(phrase in author_lower for phrase in [
                'not specified',
                'not provided',
                'not available',
                'see article',
                'full author list',
                'et al.',
                'and others',
                'review article',
                '[not',  # Catches [Not provided], [Not specified], etc.
            ]):
                # If it's the only author, reject the paper
                if len(authors) == 1:
                    logger.warning(f"Rejecting paper with invalid author: {paper.get('title', 'Unknown')}")
                    return False
        
        # Verify DOI exists in CrossRef (skip for preprints like arXiv/bioRxiv)
        doi = paper.get('doi', '')
        if doi and not any(prefix in doi for prefix in ['10.48550/', '10.1101/']):
            if not self._verify_doi(doi):
                logger.warning(f"Rejecting paper with unverified DOI: {paper.get('title', 'Unknown')}")
                return False
        
        return True

    def _verify_doi(self, doi):
        """
        Verify that a DOI exists by checking against CrossRef API.
        
        Args:
            doi (str): The DOI to verify
            
        Returns:
            bool: True if the DOI exists in CrossRef
        """
        if not doi:
            return False
        
        try:
            url = f"https://api.crossref.org/works/{doi}"
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'LiteratureMonitor/1.0 (mailto:contact@example.com)'
            })
            if response.status_code == 200:
                logger.info(f"DOI verified: {doi}")
                return True
            else:
                logger.warning(f"DOI verification failed (status {response.status_code}): {doi}")
                return False
        except requests.RequestException as e:
            logger.warning(f"DOI verification request failed for {doi}: {str(e)}")
            return False

    def generate_site(self, new_papers):
        """Generate the HTML site with all papers."""
        try:
            os.makedirs('docs', exist_ok=True)
            
            # Load historical papers from archives
            historical_papers = self.load_papers_from_archives()
            
            # Combine with new papers
            all_papers = historical_papers + new_papers
            
            # Remove duplicates based on DOI
            unique_papers = []
            seen_dois = set()
            for paper in all_papers:
                if paper.get('doi') and paper['doi'].lower() not in seen_dois:
                    unique_papers.append(paper)
                    seen_dois.add(paper['doi'].lower())
            
            # Add category to each paper before rendering
            for paper in unique_papers:
                if 'category' not in paper:
                    paper['category'] = self._categorize(paper)
            
            # Use the Jinja2 template
            template = self.template_env.get_template('index.html')
            
            with open('docs/index.html', 'w') as f:
                f.write(template.render(
                    papers=unique_papers,
                    updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    count=len(new_papers),  # Only count new papers in the update message
                    total=len(unique_papers)  # Total papers displayed
                ))
            
            logger.info(f"Generated site with {len(new_papers)} new papers and {len(unique_papers)} total papers")
        except Exception as e:
            logger.error(f"Failed to generate site: {str(e)}")
            
    def _generate_paper_summary(self, paper):
        """
        Generate an AI summary for a paper.
        
        Args:
            paper (dict): Paper metadata
            
        Returns:
            str: Summary of the paper
        """
        try:
            prompt = f"""Provide a concise 2-3 sentence technical summary of this paper:
            Title: {paper['title']}
            Authors: {'; '.join(paper['authors'])}
            DOI: {paper['doi']}
            Keywords: {', '.join(paper['keywords'])}
            
            Focus on the key innovation and potential impact for biorobotics research.
            """
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Failed to generate summary: {str(e)}")
            return "Summary unavailable due to technical error."

    def _create_archive_file(self, papers_with_summaries):
        """
        Create a markdown archive file with paper summaries.
        
        Args:
            papers_with_summaries (list): List of paper dictionaries with summaries
        """
        try:
            # Create archive directory if it doesn't exist
            archive_dir = 'src/archive'
            os.makedirs(archive_dir, exist_ok=True)
            
            # Create filename with current date
            filename = f"{archive_dir}/papers_{datetime.now().strftime('%Y-%m-%d')}.md"
            
            with open(filename, 'w') as f:
                f.write(f"# Research Papers Compilation - {datetime.now().strftime('%B %d, %Y')}\n\n")
                f.write(f"## Summary\n")
                f.write(f"This compilation contains {len(papers_with_summaries)} new papers in biorobotics research.\n\n")
                
                # Group papers by category
                categories = {}
                for paper in papers_with_summaries:
                    category = self._categorize(paper)
                    if category not in categories:
                        categories[category] = []
                    categories[category].append(paper)
                
                # Write papers by category
                for category, cat_papers in categories.items():
                    f.write(f"## {category} ({len(cat_papers)} papers)\n\n")
                    
                    for paper in cat_papers:
                        f.write(f"### {paper['title']}\n\n")
                        f.write(f"**Authors:** {'; '.join(paper['authors'])}\n\n")
                        f.write(f"**DOI:** {paper['doi']}\n\n")
                        f.write(f"**TRL:** {paper['trl']}\n\n")
                        f.write(f"**Keywords:** {', '.join(paper['keywords'])}\n\n")
                        f.write(f"**Summary:** {paper['summary']}\n\n")
                        f.write("---\n\n")
            
            logger.info(f"Created archive file: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Failed to create archive file: {str(e)}")
            return None

    def _format_category_name(self, term):
        """
        Format a search term as a category name.
        
        Args:
            term (str): The search term
            
        Returns:
            str: Formatted category name
        """
        # Capitalize each word and remove extra whitespace
        words = term.strip().split()
        return ' '.join(word.capitalize() for word in words)
    
    def execute(self):
        """Execute the literature monitoring process."""
        new_papers = []
        
        try:
            # Get existing DOIs to avoid duplicates
            existing_items = self.zot.everything(self.zot.items())
            existing_dois = {
                item['data'].get('DOI', '').lower() 
                for item in existing_items 
                if 'DOI' in item['data']
            }
            
            with ThreadPoolExecutor() as executor:
                results = list(executor.map(self._deep_research_query, self.search_terms))
                
                for term, response in results:
                    if not response:
                        continue
                    
                    papers = self._parse_response(response)
                    for paper in papers:
                        paper_doi = paper.get('doi', '').lower()
                        if paper_doi and paper_doi not in existing_dois:
                            # Store the source search term as the category
                            paper['source_term'] = term
                            # Format the term for use as a category name
                            paper['category'] = self._format_category_name(term)
                            
                            # Generate summary for the paper
                            paper['summary'] = self._generate_paper_summary(paper)
                            self._save_to_zotero(paper)
                            new_papers.append(paper)
                            existing_dois.add(paper_doi)  # Prevent duplicates within batch
            
            if new_papers:
                # Create archive file with summaries
                self._create_archive_file(new_papers)
                
                # Generate the website
                self.generate_site(new_papers)
                logger.info(f"Added {len(new_papers)} papers")
                
                # Get unique categories from the papers
                categories = list(set(paper['category'] for paper in new_papers))
                
                # Create update.json with dynamic categories
                with open('docs/update.json', 'w') as f:
                    json.dump({
                        "timestamp": datetime.now().isoformat(),
                        "count": len(new_papers),
                        "categories": {cat: sum(1 for p in new_papers if p['category'] == cat) 
                                    for cat in categories}
                    }, f, indent=2)
            else:
                logger.info("No new papers found")
                self.generate_site([])  # Generate site with no new papers
                
        except Exception as e:
            logger.error(f"Execution error: {str(e)}")
            raise

if __name__ == "__main__":
    LiteratureMonitor().execute()
