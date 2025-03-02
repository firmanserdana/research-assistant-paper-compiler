import os
import re
import json
import logging
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
    
    def __init__(self, model="sonar-pro", provider="perplexity"):
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
            else:
                return OpenAI(
                    api_key=os.getenv("PPLX_API_KEY"),
                    base_url="https://api.perplexity.ai"
                )
        except Exception as e:
            logger.error(f"Failed to initialize {provider} client: {str(e)}")
            raise

    def _categorize(self, paper):
        """
        Categorize a paper based on its title and keywords.
        
        Args:
            paper (dict): Paper metadata
            
        Returns:
            str: Category name
        """
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
            str: AI-generated research results
        """
        try:
            logger.info(f"Researching term: {term}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": f"""Provide recent peer-reviewed papers about {term} 
                    in biomedical engineering and robotics. Include DOI, TRL (1-9), and technical 
                    keywords. Format:
                    Title: [Title]
                    Authors: [Author1; Author2]
                    DOI: [DOI]
                    TRL: [Number]
                    Keywords: [Keyword1, Keyword2]"""
                }],
                temperature=0.2,
                max_tokens=2000
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"API request failed: {str(e)}")
            return ""  # Return empty string to handle gracefully
            
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
                current['title'] = line[6:].strip()
            elif line.startswith('Authors:'):
                current['authors'] = line[8:].strip().split('; ')
            elif line.startswith('DOI:'):
                current['doi'] = line[4:].strip()
            elif line.startswith('TRL:'):
                current['trl'] = int(line[4:].strip())
            elif line.startswith('Keywords:'):
                current['keywords'] = [k.strip() for k in line[9:].split(',')]
                papers.append(current)
                current = {}
                
        return [p for p in papers if self._validate(p)]

    def _validate(self, paper):
        return all([
            paper.get('doi'),
            paper.get('title'),
            len(paper.get('authors', [])) > 0,
            1 <= paper.get('trl', 0) <= 9
        ])

    def _categorize(self, paper):
        text = f"{paper['title']} {' '.join(paper['keywords'])}".lower()
        if 'biohybrid' in text:
            return 'Biohybrid Systems'
        elif 'neuromorphic' in text:
            return 'Neuromorphic Engineering'
        return 'General Biorobotics'

    def generate_site(self, papers):
        """
        Generate the HTML site with the new papers.
        
        Args:
            papers (list): List of paper dictionaries
        """
        try:
            os.makedirs('docs', exist_ok=True)
            
            # Add category to each paper before rendering
            for paper in papers:
                paper['category'] = self._categorize(paper)
                
            # Use the Jinja2 template instead of hardcoded HTML
            template = self.template_env.get_template('index.html')
            
            with open('docs/index.html', 'w') as f:
                f.write(template.render(
                    papers=papers,
                    updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    count=len(papers)
                ))
            
            logger.info(f"Generated site with {len(papers)} new papers")
        except Exception as e:
            logger.error(f"Failed to generate site: {str(e)}")

    def _parse_response(self, content):
        papers = []
        current = {}
        
        for line in content.split('\n'):
            if line.startswith('Title:'):
                current['title'] = line[6:].strip()
            elif line.startswith('Authors:'):
                current['authors'] = line[8:].strip().split('; ')
            elif line.startswith('DOI:'):
                current['doi'] = line[4:].strip()
            elif line.startswith('TRL:'):
                current['trl'] = int(line[4:].strip())
            elif line.startswith('Keywords:'):
                current['keywords'] = [k.strip() for k in line[9:].split(',')]
                papers.append(current)
                current = {}
                
        return [p for p in papers if self._validate(p)]

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
                
                for response in results:
                    if not response:
                        continue
                    
                    papers = self._parse_response(response)
                    for paper in papers:
                        paper_doi = paper.get('doi', '').lower()
                        if paper_doi and paper_doi not in existing_dois:
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
                
                # Save update metadata
                with open('docs/update.json', 'w') as f:
                    json.dump({
                        "timestamp": datetime.now().isoformat(),
                        "count": len(new_papers),
                        "categories": {cat: sum(1 for p in new_papers if self._categorize(p) == cat) 
                                     for cat in ['Biohybrid Systems', 'Neuromorphic Engineering', 
                                                'Soft Robotics', 'General Biorobotics']}
                    }, f, indent=2)
            else:
                logger.info("No new papers found")
                
        except Exception as e:
            logger.error(f"Execution error: {str(e)}")
            raise

if __name__ == "__main__":
    LiteratureMonitor().execute()
