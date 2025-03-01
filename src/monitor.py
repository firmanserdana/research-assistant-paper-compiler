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
            
        self.search_terms = [
            "biohybrid actuator design",
            "neuromorphic control in prosthetics",
            "soft robotics biomimicry"
        ]
        
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
        if 'biohybrid' in text or 'bio-hybrid' in text:
            return 'Biohybrid Systems'
        elif 'neuromorphic' in text or 'neural' in text and ('circuit' in text or 'prosthetic' in text):
            return 'Neuromorphic Engineering'
        elif 'soft' in text and ('robot' in text or 'actuator' in text):
            return 'Soft Robotics'
        
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
                    "content": f"""Provide recent (2023-2025) peer-reviewed papers about {term} 
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
            
            # Create item
            self.zot.create_items([{
                'itemType': 'journalArticle',
                'title': paper['title'],
                'creators': creators,
                'DOI': paper['doi'],
                'tags': [{'tag': k} for k in paper['keywords']],
                'collections': [self._categorize(paper)],
                'extra': f"TRL: {paper['trl']} | Added: {datetime.now().isoformat()}"
            }])
            logger.info(f"Added paper to Zotero: {paper['title']}")
        except Exception as e:
            logger.error(f"Failed to save paper to Zotero: {str(e)}")

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
                            self._save_to_zotero(paper)
                            new_papers.append(paper)
                            existing_dois.add(paper_doi)  # Prevent duplicates within batch
            
            if new_papers:
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
