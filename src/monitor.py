import os
import re
import json
import time
import logging
import html
import requests
import argparse
import sys
import email.utils
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
from jinja2 import Environment, FileSystemLoader

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('literature_monitor')

# DOI regex pattern for standard DOIs
DOI_REGEX = re.compile(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+')

# Core technical terms required for Crossref fallback relevance filtering
BIOROBOTICS_CORE_TERMS = (
    'emg', 'electromyograph', 'myoelectric', 'intracortical', 'cortical',
    'brain-computer', 'brain–computer', 'brain machine', 'bci', 'neural interface',
    'neural decod', 'motor decod', 'prosthe', 'neuroprosthe', 'robot',
    'exoskeleton', 'bionic', 'orthos', 'orthotic', 'biohybrid', 'soft actuator',
    'artificial muscle', 'functional electrical stimulation', 'nerve stimulation',
    'neurostimulat', 'peripheral nerve interface', 'cuff electrode', 'microelectrode',
    'intrafascicular', 'kinematic', 'motor unit', 'hand control', 'finger control',
    'grasp', 'spinal cord stimulation', 'epidural stimulation', 'neurorehabilitation'
)

OFF_TOPIC_CLINICAL_TERMS = (
    'self-catheterization', 'catheterization', 'bowel dysfunction', 'acute kidney injury',
    'midodrine', 'vasopressor', 'mental burden among caregivers', 'venous flap',
    'calcific tendinitis', 'hypothenar hammer', 'malignant peripheral nerve sheath',
    'forgotten contributions', 'heterotopic ossification resection'
)



class LiteratureMonitor:
    """Monitor biorobotics literature and add new papers to Zotero library and web portal."""

    PROVIDER_DEFAULT_MODELS = {
        "perplexity": "sonar-pro",
        "gemini": "gemini-2.5-flash",
        "anthropic": "claude-3-5-sonnet-latest",
        "openai": "gpt-4o-mini",
        "ollama": "llama3",
        "crossref": None,
        "arxiv": None,
        "openalex": None,
    }

    def __init__(self, model=None, provider="auto", dry_run=False, limit=None, skip_zotero=False, include_arxiv=False):
        """
        Initialize the literature monitor.

        Args:
            model (str, optional): The AI model to use. Defaults to provider default.
            provider (str): AI provider - "auto", "perplexity", "gemini", "anthropic", "openai", "ollama", "crossref", "arxiv", or "openalex"
            dry_run (bool): Run without modifying archive files or syncing to Zotero.
            limit (int, optional): Maximum papers to retrieve per search term.
            skip_zotero (bool): Skip Zotero syncing even if credentials exist.
            include_arxiv (bool): Query arXiv in addition to primary provider.
        """
        self.dry_run = dry_run
        self.limit = limit
        self.skip_zotero = skip_zotero
        self.include_arxiv = include_arxiv
        self.generate_site_only = False

        # Resolve "auto" provider based on available environment variables
        if provider == "auto":
            if os.getenv("PPLX_API_KEY"):
                provider = "perplexity"
            elif os.getenv("GEMINI_API_KEY"):
                provider = "gemini"
            elif os.getenv("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.getenv("OPENAI_API_KEY"):
                provider = "openai"
            else:
                provider = "crossref"

        # Check required environment variables for specific provider
        required_vars = []
        if provider == "perplexity" and not os.getenv("PPLX_API_KEY"):
            logger.warning("PPLX_API_KEY not found; falling back to keyless Crossref provider.")
            provider = "crossref"
        elif provider == "gemini":
            required_vars.append("GEMINI_API_KEY")
        elif provider == "anthropic":
            required_vars.append("ANTHROPIC_API_KEY")
        elif provider == "openai":
            required_vars.append("OPENAI_API_KEY")

        self._check_environment(required_vars)

        self.provider = provider
        self.model = model or self.PROVIDER_DEFAULT_MODELS.get(provider, "sonar-pro")
        self.client = None if provider in ("crossref", "arxiv", "openalex") else self._get_client(provider)

        # Setup Zotero client if credentials exist and sync is not skipped
        self.zot = None
        if not self.skip_zotero and not self.dry_run:
            zotero_id, zotero_key = os.getenv("ZOTERO_USER_ID"), os.getenv("ZOTERO_API_KEY")
            if zotero_id and zotero_key:
                try:
                    from pyzotero import zotero
                    self.zot = zotero.Zotero(zotero_id, 'user', zotero_key)
                    self.zot.collections()
                except Exception as e:
                    logger.warning(f"Zotero unavailable; continuing without library sync: {e}")

        # Read search terms from search_terms.txt
        terms_file = 'search_terms.txt'
        if os.path.exists(terms_file):
            with open(terms_file, 'r', encoding='utf-8') as f:
                self.search_terms = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        else:
            self.search_terms = [
                "EMG decoding on Spinal Cord Injured patients",
                "Intracortical Decoding on Hand and Finger kinematics",
                "Stimulating peripheral nerve to enable hand and/or finger control"
            ]

        # Setup template engine
        templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
        if not os.path.exists(templates_dir):
            templates_dir = 'src/templates'
        self.template_env = Environment(loader=FileSystemLoader(templates_dir))

    def _check_environment(self, required_vars):
        """Check if all required environment variables are set."""
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            error_msg = f"Missing environment variables: {', '.join(missing)}"
            logger.error(error_msg)
            raise EnvironmentError(error_msg)

    def _get_client(self, provider):
        """Get the appropriate API client based on the provider."""
        try:
            if provider == "anthropic":
                from anthropic import Anthropic
                return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            elif provider == "gemini":
                from openai import OpenAI
                return OpenAI(
                    api_key=os.getenv("GEMINI_API_KEY"),
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                )
            elif provider == "ollama":
                from openai import OpenAI
                base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
                return OpenAI(base_url=base_url)
            elif provider == "openai":
                from openai import OpenAI
                return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            else:
                from openai import OpenAI
                return OpenAI(
                    api_key=os.getenv("PPLX_API_KEY"),
                    base_url="https://api.perplexity.ai"
                )
        except Exception as e:
            logger.error(f"Failed to initialize {provider} client: {str(e)}")
            raise

    def _call_llm(self, prompt, system_prompt=None, max_tokens=1500, temperature=0.2):
        """Unified LLM call supporting Anthropic and OpenAI-compatible APIs."""
        if not self.client:
            return None

        if self.provider == "anthropic":
            messages = [{"role": "user", "content": prompt}]
            kwargs = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            response = self.client.messages.create(**kwargs)
            return response.content[0].text
        else:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content

    def _clean_jats_abstract(self, raw_abstract):
        """Clean JATS XML / HTML tags and decode entities from Crossref abstracts."""
        if not raw_abstract:
            return ""
        # Remove XML/HTML tags
        clean = re.sub(r'<[^>]+>', ' ', raw_abstract)
        # Unescape HTML entities
        clean = html.unescape(clean)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def _normalize_doi(self, doi):
        """
        Normalize a DOI by removing URL prefixes, reference citation brackets, and trailing artifacts.
        Preserves valid trailing digits in the DOI suffix.
        """
        if not doi or not isinstance(doi, str):
            return ""

        doi = doi.strip()

        # Reject common placeholder texts
        lower_doi = doi.lower().strip()
        if lower_doi in {'n/a', 'none', 'unknown', 'na', 'null'}:
            return ""
        phrase_placeholders = [
            'not provided', 'not specified', 'not available', 'see article', '[not'
        ]
        if any(p in lower_doi for p in phrase_placeholders):
            return ""

        # Remove bracketed placeholders like [DOI] or [Not provided in search results]
        if doi.startswith('[') and doi.endswith(']'):
            return ""

        # Remove common URL and scheme prefixes
        prefixes = [
            'https://doi.org/', 'http://doi.org/', 'doi.org/',
            'https://dx.doi.org/', 'http://dx.doi.org/', 'dx.doi.org/',
            'doi:', 'DOI: ', 'DOI:'
        ]
        for prefix in prefixes:
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix):].strip()

        # Remove citation numbers with brackets like [1], [2], [12] ONLY
        # DO NOT use optional brackets (\[?\d+\]?) which strips valid digits!
        doi = re.sub(r'\[\d+\]$', '', doi).strip()

        # Remove parenthetical info at the very end
        doi = re.sub(r'\s*\([^)]*\)$', '', doi).strip()

        # Remove trailing periods, slashes, or commas that are often punctuation
        doi = doi.rstrip('./,; ')

        # If a valid DOI is embedded in remaining text, extract it
        match = DOI_REGEX.search(doi)
        if match:
            return match.group(0)

        # Fallback: check if it looks like a DOI prefix
        if doi.startswith('10.'):
            return doi

        return ""

    def _compute_title_similarity(self, title1, title2):
        """Compute normalized similarity between two paper titles (0.0 to 1.0)."""
        if not title1 or not title2:
            return 0.0

        def norm(s):
            s = html.unescape(s).lower()
            s = re.sub(r'<[^>]+>', ' ', s)
            s = re.sub(r'[^\w\s]', ' ', s)
            return re.sub(r'\s+', ' ', s).strip()

        n1, n2 = norm(title1), norm(title2)
        if not n1 or not n2:
            return 0.0
        if n1 == n2:
            return 1.0

        shorter, longer = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
        if len(shorter) >= 25 and (len(shorter) / len(longer)) >= 0.50 and shorter in longer:
            return 0.90

        seq_ratio = SequenceMatcher(None, n1, n2).ratio()
        stop = {'the', 'a', 'an', 'of', 'in', 'on', 'for', 'and', 'to', 'with', 'by', 'from', 'at', 'using', 'via', 'based'}
        w1 = {w for w in n1.split() if w not in stop and len(w) > 2}
        w2 = {w for w in n2.split() if w not in stop and len(w) > 2}
        if not w1 or not w2:
            return seq_ratio
        overlap = len(w1 & w2) / max(len(w1), len(w2))
        return max(seq_ratio, overlap * 0.95)

    def _clean_citation_artifacts(self, text):
        """Remove LLM reference brackets such as [1], [2, 3] from text."""
        if not text or not isinstance(text, str):
            return ""
        cleaned = re.sub(r'\s*\[\d+(?:\s*,\s*\d+)*\]', '', text)
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _is_relevant_to_biorobotics(self, title, abstract="", subjects=None):
        """
        Check whether a scholarly work is relevant to biorobotics, neural decoding,
        or neuroprosthetics, filtering out unrelated clinical case reports.
        """
        combined = f"{title} {abstract} {' '.join(subjects or [])}".lower()
        if any(bad in combined for bad in OFF_TOPIC_CLINICAL_TERMS):
            return False
        return any(term in combined for term in BIOROBOTICS_CORE_TERMS)

    def _verify_doi(self, doi, expected_title=None):
        """
        Verify that a DOI exists by checking against CrossRef API (and optionally verifying title similarity).
        """
        if not doi:
            return False

        # Preprints don't always resolve via Crossref works API
        if any(prefix in doi for prefix in ['10.48550/', '10.1101/', '10.31219/', 'arXiv']):
            return True

        if not DOI_REGEX.match(doi):
            return False

        try:
            url = f"https://api.crossref.org/works/{doi}"
            response = requests.get(
                url,
                timeout=10,
                headers={'User-Agent': 'LiteratureMonitor/1.0 (mailto:contact@example.com)'}
            )
            if response.status_code == 200:
                data = response.json().get('message', {})
                titles = data.get('title', [])
                cr_title = titles[0] if titles else ""
                # Ensure it has a title or work type to avoid bare publisher prefixes
                if cr_title or data.get('type'):
                    if expected_title and cr_title:
                        sim = self._compute_title_similarity(expected_title, cr_title)
                        if sim < 0.65:
                            logger.warning(
                                f"DOI title mismatch for {doi} (sim={sim:.2f}): "
                                f"expected '{expected_title[:60]}' vs Crossref '{cr_title[:60]}'"
                            )
                            return False
                    logger.info(f"DOI verified: {doi}")
                    return True
            logger.warning(f"DOI verification failed (status {response.status_code}): {doi}")
            return False
        except requests.RequestException as e:
            logger.warning(f"DOI verification request failed for {doi}: {str(e)}")
            # On transient network failure, don't drop papers with valid DOI patterns
            return True

    def _estimate_trl(self, title, summary="", keywords=None, current_trl=None):
        """
        Estimate Technology Readiness Level (TRL 1-8) from clinical, preclinical,
        and engineering evidence in the paper's title, summary, and keywords.
        """
        if current_trl and int(current_trl) > 2:
            return int(current_trl)

        kw_str = " ".join(keywords or []) if isinstance(keywords, list) else str(keywords or "")
        title_l = (title or "").lower()
        text = f"{title_l} {(summary or '').lower()} {kw_str.lower()}"

        # Review / Survey / Perspective -> TRL 2
        if any(w in title_l for w in ("review", "survey", "meta-analysis", "perspective", "overview", "scoping")):
            return 2

        # Long-term home / clinical trial -> TRL 7
        if any(w in text for w in ("home use", "take-home", "daily life", "home-use", "multi-center clinical trial", "clinical trial")) and any(
            c in text for c in ("patient", "tetraplegi", "paraplegi", "amputee", "participant", "human")
        ):
            return 7

        # Closed-loop / implanted / real-time human clinical validation -> TRL 6
        if any(c in text for c in ("tetraplegi", "paraplegi", "amputee", "spinal cord injur", "sci patient", "human participant", "in humans", "patients with")) and any(
            s in text for s in ("closed-loop", "prosthe", "bionic", "intracortical", "implanted", "epidural", "neuroprosthe", "real-time", "exoskeleton", "sensory feedback", "functional electrical stimulation")
        ):
            return 6

        # Human clinical feasibility / rehabilitation / surface EMG in patients -> TRL 5
        if any(c in text for c in ("patient", "clinical", "tetraplegi", "paraplegi", "amputee", "rehabilitation", "subacute", "chronic care", "stroke")):
            return 5

        # Non-human primate / animal in-vivo / hardware prototype / real-time healthy human -> TRL 4
        if any(p in text for p in ("macaque", "monkey", "primate", "rhesus", "in vivo", "in-vivo", "rat", "rodent", "porcine", "prototype", "real-time", "able-bodied", "healthy subject", "myoelectric control", "cuff electrode", "soft robotic")):
            return 4

        # Offline decoding / algorithm / simulation / dataset -> TRL 3
        if any(a in text for a in ("decoding", "classification", "neural network", "convolutional", "kalman", "kinematic", "simulation", "algorithm", "dataset")):
            return 3

        return int(current_trl) if current_trl else 2

    def _reconstruct_openalex_abstract(self, inverted_index):
        """Reconstruct plain-text abstract from an OpenAlex abstract_inverted_index dictionary."""
        if not inverted_index or not isinstance(inverted_index, dict):
            return ""
        positions = {}
        for word, pos_list in inverted_index.items():
            if isinstance(pos_list, list):
                for p in pos_list:
                    if isinstance(p, int):
                        positions[p] = word
        if not positions:
            return ""
        ordered_words = [positions[idx] for idx in sorted(positions.keys())]
        return self._clean_jats_abstract(" ".join(ordered_words))

    def _openalex_search(self, term, rows=15, filter_str="from_publication_date:2021-01-01,type:article"):
        """Find recent scholarly works via the keyless OpenAlex API with abstracts, citations, and OA PDFs."""
        try:
            response = requests.get(
                "https://api.openalex.org/works",
                params={
                    "search": term,
                    "filter": filter_str,
                    "per-page": rows,
                    "mailto": "literature-monitor@example.com"
                },
                timeout=25,
                headers={"User-Agent": "LiteratureMonitor/2.0 (mailto:literature-monitor@example.com)"},
            )
            response.raise_for_status()
            items = response.json().get("results", [])
            records = []
            for item in items:
                title = self._clean_jats_abstract((item.get("title") or "").strip())
                raw_doi = (item.get("doi") or "").replace("https://doi.org/", "").strip()
                doi = self._normalize_doi(raw_doi)
                authors = [
                    (a.get("author") or {}).get("display_name", "").strip()
                    for a in item.get("authorships", [])
                ]
                authors = [a for a in authors if a]
                if not title or not doi or not authors:
                    continue

                clean_abstract = self._reconstruct_openalex_abstract(item.get("abstract_inverted_index"))
                concepts = [
                    c.get("display_name", "")
                    for c in (item.get("concepts") or [])[:6]
                    if c.get("display_name")
                ]
                keywords = concepts or [term]

                if not self._is_relevant_to_biorobotics(title, clean_abstract, keywords):
                    continue

                trl = self._estimate_trl(title, clean_abstract, keywords)
                loc = item.get("primary_location") or {}
                oa = item.get("open_access") or {}
                pdf_url = loc.get("pdf_url") or oa.get("oa_url") or ""
                if not pdf_url and doi.lower().startswith("10.48550/arxiv."):
                    pdf_url = f"https://arxiv.org/pdf/{doi.lower().split('arxiv.')[-1]}.pdf"
                venue = ((loc.get("source") or {}).get("display_name") or "").strip()
                pub_year = str(item.get("publication_year") or "")
                citations = int(item.get("cited_by_count") or 0)

                if not hasattr(self, "_runtime_scholarly_cache"):
                    self._runtime_scholarly_cache = {}
                self._runtime_scholarly_cache[doi.lower()] = {
                    "pub_year": pub_year,
                    "venue": venue or ("arXiv" if "arxiv" in doi.lower() else ""),
                    "citations": citations,
                    "oa_url": pdf_url,
                }

                record_lines = [
                    f"Title: {title}",
                    f"Authors: {'; '.join(authors)}",
                    f"DOI: {doi}",
                    f"TRL: {trl}",
                    f"Keywords: {', '.join(keywords)}"
                ]
                if clean_abstract:
                    snippet = clean_abstract[:450] + ("..." if len(clean_abstract) > 450 else "")
                    record_lines.append(f"Summary: {snippet}")
                if pdf_url:
                    record_lines.append(f"PDF: {pdf_url}")

                record_lines.append("")
                records.extend(record_lines)

            return "\n".join(records)
        except Exception as e:
            logger.error(f"OpenAlex query error for {term}: {e}")
            return ""

    def _deep_research_query(self, term):
        """Query AI provider, arXiv, OpenAlex, or Crossref for recent papers on a specific term."""
        try:
            logger.info(f"Researching term: {term}")
            if self.provider == "arxiv":
                return (term, self._arxiv_search(term, max_results=self.limit or 10))
            elif self.provider == "openalex":
                return (term, self._openalex_search(term, rows=self.limit or 15))
            elif self.provider == "crossref":
                return (term, self._crossref_search(term, rows=self.limit or 15))

            prompt = f"""Provide recent peer-reviewed papers about {term} 
in biomedical engineering and robotics. Include DOI (without URL prefix), TRL (1-9), and technical keywords.
Format each paper exactly as:
Title: [Title]
Authors: [Author1; Author2; Author3]
DOI: [DOI number only, e.g., 10.1234/example]
TRL: [Number 1-9]
Keywords: [Keyword1, Keyword2]
Summary: [2-3 sentence technical summary]

IMPORTANT:
- Provide actual author names, not placeholders
- Provide only the DOI number (e.g., 10.1234/example), not the full URL
- Skip papers where author information or DOI is unavailable"""

            response_content = self._call_llm(
                prompt=prompt,
                system_prompt="You are an expert biorobotics and biomedical engineering research assistant.",
                temperature=0.2,
                max_tokens=2000
            )

            if not response_content:
                logger.warning(f"Empty AI response for {term}; falling back to Crossref.")
                return (term, self._crossref_search(term))

            return (term, response_content)
        except Exception as e:
            logger.warning(f"AI search failed for {term}; using Crossref fallback: {e}")
            try:
                return (term, self._crossref_search(term))
            except Exception as fallback_error:
                logger.error(f"Crossref search failed for {term}: {fallback_error}")
                return (term, "")

    def _arxiv_search(self, term, max_results=10):
        """Find relevant preprints via arXiv API without an API key, with OpenAlex arXiv index fallback."""
        try:
            stopwords = {
                'on', 'to', 'enable', 'and/or', 'and', 'or', 'the', 'in', 'of',
                'for', 'with', 'patients', 'injured', 'stimulating'
            }
            tokens = [
                w for w in re.sub(r'["/]', ' ', term).split()
                if w.lower() not in stopwords
            ][:3]
            if tokens:
                query_expr = "+AND+".join(f"all:{urllib.parse.quote(t)}" for t in tokens)
            else:
                stripped_term = term.replace('"', '').strip()
                query_expr = f"all:{urllib.parse.quote(stripped_term)}"
            fetch_count = max(max_results * 3, 10) if max_results > 1 else max_results
            url = (
                f"https://export.arxiv.org/api/query?"
                f"search_query={query_expr}&start=0&max_results={fetch_count}"
                f"&sortBy=relevance&sortOrder=descending"
            )
            headers = {"User-Agent": "LiteratureMonitor/2.0 (mailto:literature-monitor@example.com)"}
            response = requests.get(url, timeout=10, headers=headers)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'arxiv': 'http://arxiv.org/schemas/atom'
            }

            records = []
            matched_count = 0
            for entry in root.findall('atom:entry', ns):
                if matched_count >= max_results:
                    break
                raw_title = entry.find('atom:title', ns)
                title = re.sub(r'\s+', ' ', raw_title.text.strip()) if raw_title is not None and raw_title.text else ""

                authors = [
                    a.find('atom:name', ns).text.strip()
                    for a in entry.findall('atom:author', ns)
                    if a.find('atom:name', ns) is not None and a.find('atom:name', ns).text
                ]

                # Extract arXiv ID (e.g., http://arxiv.org/abs/2401.12345v1 -> 2401.12345)
                id_elem = entry.find('atom:id', ns)
                raw_id = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
                arxiv_id = raw_id.split('/abs/')[-1].strip() if '/abs/' in raw_id else raw_id
                base_arxiv_id = re.sub(r'v\d+$', '', arxiv_id)

                doi_elem = entry.find('arxiv:doi', ns)
                if doi_elem is not None and doi_elem.text:
                    doi = self._normalize_doi(doi_elem.text.strip())
                else:
                    doi = f"10.48550/arXiv.{base_arxiv_id}" if base_arxiv_id else ""

                pdf_url = f"https://arxiv.org/pdf/{base_arxiv_id}.pdf" if base_arxiv_id else ""

                summary_elem = entry.find('atom:summary', ns)
                summary = re.sub(r'\s+', ' ', summary_elem.text.strip()) if summary_elem is not None and summary_elem.text else ""

                keywords = [
                    c.attrib.get('term', '')
                    for c in entry.findall('atom:category', ns)
                    if c.attrib.get('term')
                ][:5] or [term]

                if not title or not doi or not authors:
                    continue

                if not self._is_relevant_to_biorobotics(title, summary, keywords):
                    continue

                record_lines = [
                    f"Title: {title}",
                    f"Authors: {'; '.join(authors)}",
                    f"DOI: {doi}",
                    "TRL: 2",
                    f"Keywords: {', '.join(keywords)}",
                ]
                if summary:
                    record_lines.append(f"Summary: {summary[:500]}")
                if pdf_url:
                    record_lines.append(f"PDF: {pdf_url}")

                record_lines.append("")
                records.extend(record_lines)
                matched_count += 1

            if records:
                logger.info(f"Retrieved {matched_count} relevant arXiv entries for: {term}")
                return "\n".join(records)

            logger.info(f"No direct arXiv matches for '{term}'; querying OpenAlex arXiv index...")
            return self._openalex_search(term, rows=max(max_results * 2, 10), filter_str="indexed_in:arxiv")
        except Exception as e:
            logger.warning(f"export.arxiv.org unavailable for '{term}' ({e}); using OpenAlex arXiv index fallback...")
            return self._openalex_search(term, rows=max(max_results * 2, 10), filter_str="indexed_in:arxiv")

    def _crossref_search(self, term, rows=20):
        """Find recent scholarly works through Crossref without an API key, filtered for biorobotics relevance."""
        try:
            response = requests.get(
                "https://api.crossref.org/works",
                params={
                    "query.bibliographic": term,
                    "filter": "from-pub-date:2021-01-01,type:journal-article",
                    "rows": rows,
                    "select": "title,author,DOI,published,subject,abstract,link"
                },
                timeout=25,
                headers={"User-Agent": "LiteratureMonitor/1.0 (mailto:contact@example.com)"},
            )
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
            records = []
            for item in items:
                title = self._clean_jats_abstract((item.get("title") or [""])[0].strip())
                doi = self._normalize_doi(item.get("DOI", ""))
                authors = [
                    " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
                    for a in item.get("author", [])
                ]
                authors = [a for a in authors if a]
                if not title or not doi or not authors:
                    continue

                subjects = item.get("subject", [])[:6]
                keywords = subjects or [term]
                raw_abstract = item.get("abstract", "")
                clean_abstract = self._clean_jats_abstract(raw_abstract)

                # Filter out off-topic clinical case reports that lack biorobotics relevance
                if not self._is_relevant_to_biorobotics(title, clean_abstract, subjects):
                    logger.debug(f"Skipping off-topic Crossref item: {title}")
                    continue

                # Skip items that have no abstract unless the title itself is strongly technical
                if not clean_abstract and not self._is_relevant_to_biorobotics(title):
                    continue

                # Attempt Open Access / direct PDF URL detection
                pdf_url = ""
                for link_item in item.get("link", []):
                    if "pdf" in link_item.get("content-type", "").lower():
                        pdf_url = link_item.get("URL", "")
                        break
                if not pdf_url:
                    if doi.lower().startswith("10.48550/arxiv."):
                        arx_id = doi.lower().split("arxiv.")[-1]
                        pdf_url = f"https://arxiv.org/pdf/{arx_id}.pdf"
                    elif doi.startswith("10.1101/"):
                        pdf_url = f"https://www.biorxiv.org/content/{doi}.full.pdf"

                est_trl = self._estimate_trl(title, clean_abstract, keywords, current_trl=2)

                record_lines = [
                    f"Title: {title}",
                    f"Authors: {'; '.join(authors)}",
                    f"DOI: {doi}",
                    f"TRL: {est_trl}",
                    f"Keywords: {', '.join(keywords)}"
                ]
                if clean_abstract:
                    # Use abstract as summary if available
                    snippet = clean_abstract[:450] + ("..." if len(clean_abstract) > 450 else "")
                    record_lines.append(f"Summary: {snippet}")
                if pdf_url:
                    record_lines.append(f"PDF: {pdf_url}")

                record_lines.append("")
                records.extend(record_lines)

            return "\n".join(records)
        except Exception as e:
            logger.error(f"Crossref query error for {term}: {e}")
            return ""

    def _parse_response(self, content):
        """Parse papers from AI, arXiv, or Crossref formatted response text."""
        papers = []
        current = {}
        in_summary = False

        title_re = re.compile(r'^\s*(?:\d+[\.\)]|\*|-)?\s*\*{0,2}Title(?:\*{0,2}\s*:\s*\*{0,2}|:\s*)\s*(.*?)(?:\*{2})?$', re.IGNORECASE)
        authors_re = re.compile(r'^\s*(?:\*|-)?\s*\*{0,2}Authors?(?:\*{0,2}\s*:\s*\*{0,2}|:\s*)\s*(.*?)(?:\*{2})?$', re.IGNORECASE)
        doi_re = re.compile(r'^\s*(?:\*|-)?\s*\*{0,2}DOI(?:\*{0,2}\s*:\s*\*{0,2}|:\s*)\s*(.*?)(?:\*{2})?$', re.IGNORECASE)
        trl_re = re.compile(r'^\s*(?:\*|-)?\s*\*{0,2}TRL(?:\*{0,2}\s*:\s*\*{0,2}|:\s*)\s*(.*?)(?:\*{2})?$', re.IGNORECASE)
        keywords_re = re.compile(r'^\s*(?:\*|-)?\s*\*{0,2}Keywords?(?:\*{0,2}\s*:\s*\*{0,2}|:\s*)\s*(.*?)(?:\*{2})?$', re.IGNORECASE)
        summary_re = re.compile(r'^\s*(?:\*|-)?\s*\*{0,2}Summary(?:\*{0,2}\s*:\s*\*{0,2}|:\s*)\s*(.*?)(?:\*{2})?$', re.IGNORECASE)
        pdf_re = re.compile(r'^\s*(?:\*|-)?\s*\*{0,2}PDF(?:\*{0,2}\s*:\s*\*{0,2}|:\s*)\s*(.*?)(?:\*{2})?$', re.IGNORECASE)

        for line in content.split('\n'):
            line_str = line.strip()

            t_match = title_re.match(line_str)
            if t_match:
                if current.get('title'):
                    papers.append(current)
                    current = {}
                in_summary = False
                current['title'] = self._clean_citation_artifacts(t_match.group(1).strip().strip('*').strip())
                continue

            a_match = authors_re.match(line_str)
            if a_match:
                in_summary = False
                authors_raw = self._clean_citation_artifacts(a_match.group(1).strip().strip('*').strip())
                if ';' in authors_raw:
                    current['authors'] = [a.strip() for a in authors_raw.split(';') if a.strip()]
                else:
                    current['authors'] = [a.strip() for a in authors_raw.split(',') if a.strip()]
                continue

            d_match = doi_re.match(line_str)
            if d_match:
                in_summary = False
                current['doi'] = self._normalize_doi(d_match.group(1).strip().strip('*').strip())
                continue

            trl_match = trl_re.match(line_str)
            if trl_match:
                in_summary = False
                trl_text = trl_match.group(1).strip().strip('*').strip()
                nums = re.findall(r'\d+', trl_text)
                if nums:
                    val = int(nums[0])
                    current['trl'] = val if 1 <= val <= 9 else 1
                else:
                    current['trl'] = 1
                continue

            k_match = keywords_re.match(line_str)
            if k_match:
                in_summary = False
                current['keywords'] = [
                    self._clean_citation_artifacts(k.strip().strip('*').strip())
                    for k in k_match.group(1).split(',')
                    if self._clean_citation_artifacts(k.strip().strip('*').strip())
                ]
                continue

            s_match = summary_re.match(line_str)
            if s_match:
                in_summary = True
                current['summary'] = self._clean_citation_artifacts(s_match.group(1).strip().strip('*').strip())
                continue

            p_match = pdf_re.match(line_str)
            if p_match:
                in_summary = False
                current['pdf_url'] = p_match.group(1).strip().strip('*').strip()
                continue

            # Multi-line summary continuation
            if in_summary and line_str and not line_str.startswith('---'):
                current['summary'] = self._clean_citation_artifacts((current.get('summary', '') + ' ' + line_str).strip())

        if current.get('title'):
            papers.append(current)

        # Set sensible defaults for missing fields
        for p in papers:
            if 'trl' not in p:
                p['trl'] = 1
            if 'keywords' not in p:
                p['keywords'] = ['biorobotics']
            if 'summary' not in p:
                p['summary'] = ''
            if not p.get('pdf_url'):
                p_doi = p.get('doi', '').lower()
                if p_doi.startswith('10.48550/arxiv.'):
                    p['pdf_url'] = f"https://arxiv.org/pdf/{p_doi.split('arxiv.')[-1]}.pdf"
                elif p_doi.startswith('10.1101/'):
                    p['pdf_url'] = f"https://www.biorxiv.org/content/{p.get('doi')}.full.pdf"

        return [p for p in papers if self._validate(p)]

    def _validate(self, paper):
        """Validate that a paper has required fields and valid DOI."""
        title = paper.get('title', '').strip()
        doi = self._normalize_doi(paper.get('doi', ''))
        authors = paper.get('authors', [])

        if not title or len(title) < 5:
            return False

        if not doi:
            logger.warning(f"Rejecting paper with missing/invalid DOI: {title}")
            return False

        if not authors:
            return False

        # Filter out placeholder authors
        placeholder_authors = [
            'not specified', 'not provided', 'not available', 'see article',
            'full author list', 'et al.', 'and others', 'review article', '[not'
        ]
        for a in authors:
            if any(p in a.lower() for p in placeholder_authors) and len(authors) == 1:
                logger.warning(f"Rejecting paper with placeholder author: {title}")
                return False

        # Verify DOI and title match against Crossref when using AI provider
        if self.provider not in ("crossref", "arxiv") and not any(pre in doi for pre in ['10.48550/', '10.1101/', '10.31219/', 'arXiv']):
            if not self._verify_doi(doi, expected_title=title):
                logger.warning(f"Rejecting paper with unverified or mismatched DOI: {title} ({doi})")
                return False

        return True

    def _parse_archive_markdown(self, content):
        """
        Parse papers from an archive markdown file.
        Robust against multi-line summaries, category headers, and various formats.
        """
        papers = []
        current_paper = None
        current_category = "General Biorobotics"
        in_summary = False

        for line in content.split('\n'):
            line_stripped = line.strip()

            # Detect category headers (e.g. ## Category Name (N papers) or ## Category Name)
            if line_stripped.startswith('## ') and not any(
                line_stripped.startswith(skip) for skip in [
                    '## Summary', '## Removed Papers', '## Verified Papers'
                ]
            ):
                in_summary = False
                cat = line_stripped[3:].strip()
                if '(' in cat and cat.endswith(')'):
                    cat = cat.rsplit('(', 1)[0].strip()
                current_category = cat

            # Detect paper title (### Title)
            elif line_stripped.startswith('### '):
                if current_paper and current_paper.get('title'):
                    papers.append(current_paper)
                in_summary = False
                current_paper = {
                    'title': line_stripped[4:].strip(),
                    'category': current_category,
                    'authors': [],
                    'doi': '',
                    'trl': 1,
                    'keywords': [],
                    'summary': '',
                    'pdf_url': ''
                }

            elif current_paper:
                if line_stripped.startswith('**Authors:**'):
                    in_summary = False
                    authors_str = line_stripped[12:].strip()
                    if ';' in authors_str:
                        current_paper['authors'] = [a.strip() for a in authors_str.split(';') if a.strip()]
                    else:
                        current_paper['authors'] = [a.strip() for a in authors_str.split(',') if a.strip()]

                elif line_stripped.startswith('**DOI:**'):
                    in_summary = False
                    current_paper['doi'] = self._normalize_doi(line_stripped[8:].strip())

                elif line_stripped.startswith('**TRL:**'):
                    in_summary = False
                    nums = re.findall(r'\d+', line_stripped[8:])
                    current_paper['trl'] = int(nums[0]) if nums else 1

                elif line_stripped.startswith('**Keywords:**'):
                    in_summary = False
                    current_paper['keywords'] = [
                        self._clean_citation_artifacts(k.strip())
                        for k in line_stripped[13:].split(',')
                        if self._clean_citation_artifacts(k.strip())
                    ]

                elif line_stripped.startswith('**Summary:**'):
                    in_summary = True
                    sum_text = line_stripped[12:].strip()
                    if sum_text.endswith('---'):
                        sum_text = sum_text[:-3].strip()
                    current_paper['summary'] = self._clean_citation_artifacts(sum_text)

                elif line_stripped.startswith('**PDF:**'):
                    in_summary = False
                    current_paper['pdf_url'] = line_stripped[8:].strip()

                elif line_stripped.startswith('---'):
                    in_summary = False

                elif in_summary and line_stripped:
                    # Multi-line summary continuation
                    clean_line = line_stripped
                    if clean_line.endswith('---'):
                        clean_line = clean_line[:-3].strip()
                        in_summary = False
                    if clean_line:
                        current_paper['summary'] = self._clean_citation_artifacts(
                            (current_paper['summary'] + ' ' + clean_line).strip()
                        )

        if current_paper and current_paper.get('title'):
            papers.append(current_paper)

        for p in papers:
            if not p.get('pdf_url'):
                p_doi = p.get('doi', '').lower()
                if p_doi.startswith('10.48550/arxiv.'):
                    p['pdf_url'] = f"https://arxiv.org/pdf/{p_doi.split('arxiv.')[-1]}.pdf"
                elif p_doi.startswith('10.1101/'):
                    p['pdf_url'] = f"https://www.biorxiv.org/content/{p.get('doi')}.full.pdf"

        return papers

    def load_papers_from_archives(self):
        """Load papers from all archive Markdown files in src/archive."""
        all_papers = []
        archive_dir = 'src/archive'

        if not os.path.exists(archive_dir):
            return all_papers

        archive_files = sorted(
            [f for f in os.listdir(archive_dir) if f.startswith('papers_') and f.endswith('.md')]
        )

        for filename in archive_files:
            try:
                filepath = os.path.join(archive_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                papers = self._parse_archive_markdown(content)
                # Attach archive source date for sorting
                archive_date = filename.replace('papers_', '').replace('.md', '')
                for p in papers:
                    p['archive_date'] = archive_date
                all_papers.extend(papers)
            except Exception as e:
                logger.error(f"Failed to load papers from {filename}: {str(e)}")

        return all_papers

    def _normalize_category(self, cat):
        """Canonicalize category name for consistent display and filtering."""
        if not cat:
            return "General Biorobotics"
        cat = re.sub(r'\bEmg\b', 'EMG', cat, flags=re.IGNORECASE)
        words = cat.split()
        normalized = []
        for w in words:
            if w.upper() in ('EMG', 'EEG', 'TRL', 'AI', 'DOI'):
                normalized.append(w.upper())
            elif w.lower() in ('on', 'and', 'or', 'to', 'in', 'the', 'for', 'with', 'of'):
                normalized.append(w.lower())
            else:
                normalized.append(w.capitalize())
        if normalized:
            if normalized[0].upper() == 'EMG':
                normalized[0] = 'EMG'
            else:
                normalized[0] = normalized[0].capitalize()
        return ' '.join(normalized)

    def _categorize(self, paper):
        """Categorize a paper based on its category, source term, or text contents."""
        raw_cat = paper.get('category')
        if raw_cat and raw_cat != "Unknown":
            return self._normalize_category(raw_cat)

        text = f"{paper.get('title', '')} {' '.join(paper.get('keywords', []))}".lower()

        if 'emg' in text or 'electromyograph' in text:
            return 'EMG Decoding on Spinal Cord Injured Patients'
        elif 'intracortical' in text or 'cortical' in text:
            return 'Intracortical Decoding on Hand and Finger Kinematics'
        elif 'stimulation' in text or 'stimulat' in text or 'cuff' in text:
            return 'Stimulating Peripheral Nerve to Enable Hand and/or Finger Control'
        elif 'biohybrid' in text:
            return 'Biohybrid Systems'
        elif 'prosthet' in text:
            return 'Neuroprosthetics'
        elif 'soft robot' in text:
            return 'Soft Robotics'

        return 'General Biorobotics'

    def _format_category_name(self, term):
        """Format a search term as a category name."""
        return self._normalize_category(term)

    def _generate_paper_summary(self, paper):
        """Generate an informative summary for a paper using AI or metadata fallback."""
        if not self.client:
            if paper.get('summary'):
                return paper['summary']
            kw = ', '.join(paper.get('keywords', [])[:3])
            return f"Recent research in {paper.get('category', 'biorobotics')} addressing {paper.get('title', '').rstrip('.')}. Key topics: {kw}."

        try:
            prompt = f"""Provide a concise 2-3 sentence technical summary of this biorobotics research paper:
Title: {paper['title']}
Authors: {'; '.join(paper['authors'])}
DOI: {paper['doi']}
Keywords: {', '.join(paper['keywords'])}

Focus on the core engineering innovation, method, and impact for biomedical robotics. Do not repeat the title verbatim."""

            summary = self._call_llm(
                prompt=prompt,
                system_prompt="You are a research summarizer specializing in biorobotics and neuroengineering.",
                max_tokens=250,
                temperature=0.3
            )
            return summary.strip() if summary else paper.get('summary', '')
        except Exception as e:
            logger.error(f"Failed to generate summary: {str(e)}")
            if paper.get('summary'):
                return paper['summary']
            return f"Technical research in {paper.get('category', 'biorobotics')} examining {paper.get('title', '').rstrip('.')}."

    def _save_to_zotero(self, paper):
        """Save a paper to the Zotero library if credentials are configured."""
        if not self.zot:
            logger.info(f"Skipping Zotero sync (credentials unavailable): {paper['title']}")
            return None

        try:
            creators = []
            for author in paper.get('authors', []):
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

            category_name = self._categorize(paper)
            collection_id = self._get_or_create_collection(category_name)

            doi = paper.get('doi', '')
            item = {
                'itemType': 'journalArticle',
                'title': paper['title'],
                'creators': creators,
                'DOI': doi,
                'abstractNote': paper.get('summary', ''),
                'publicationTitle': paper.get('venue', ''),
                'date': str(paper.get('pub_year') or datetime.now().year),
                'url': paper.get('pdf_url') or (f"https://doi.org/{doi}" if doi else ""),
                'tags': [{'tag': k} for k in paper.get('keywords', [])],
                'collections': [collection_id] if collection_id else [],
                'extra': f"TRL: {paper.get('trl', 1)} | Added: {datetime.now().isoformat()}"
            }
            result = self.zot.create_items([item])
            logger.info(f"Added paper to Zotero: {paper['title']}")
            return result
        except Exception as e:
            logger.error(f"Failed to save paper to Zotero: {str(e)}")
            return None

    def _get_or_create_collection(self, category_name):
        """Get or create a Zotero collection by name, with in-memory caching."""
        if not self.zot:
            return None
        try:
            if not hasattr(self, '_zotero_collection_cache'):
                self._zotero_collection_cache = {}
                for col in self.zot.collections():
                    c_name = col.get('data', {}).get('name')
                    if c_name and col.get('key'):
                        self._zotero_collection_cache[c_name] = col['key']

            if category_name in self._zotero_collection_cache:
                return self._zotero_collection_cache[category_name]

            res = self.zot.create_collections([{'name': category_name}])
            if res and 'successful' in res and res['successful']:
                key = res['successful']['0']
                if isinstance(key, dict):
                    key = key.get('key')
                self._zotero_collection_cache[category_name] = key
                return key
            return None
        except Exception as e:
            logger.error(f"Error with Zotero collection: {str(e)}")
            return None

    def _create_archive_file(self, papers_with_summaries, archive_dir='src/archive'):
        """Create or merge into today's markdown archive file without overwriting earlier same-day papers."""
        try:
            os.makedirs(archive_dir, exist_ok=True)
            today_str = datetime.now().strftime('%Y-%m-%d')
            filename = os.path.join(archive_dir, f"papers_{today_str}.md")

            merged_by_doi = {}
            if os.path.exists(filename):
                try:
                    with open(filename, 'r', encoding='utf-8') as existing_f:
                        existing_papers = self._parse_archive_markdown(existing_f.read())
                    for ep in existing_papers:
                        ep_doi = self._normalize_doi(ep.get('doi', '')).lower()
                        if ep_doi:
                            merged_by_doi[ep_doi] = ep
                except Exception as e:
                    logger.warning(f"Could not read existing archive {filename} for merge: {e}")

            for paper in papers_with_summaries:
                p_doi = self._normalize_doi(paper.get('doi', '')).lower()
                if p_doi:
                    merged_by_doi[p_doi] = paper

            all_today_papers = list(merged_by_doi.values()) if merged_by_doi else list(papers_with_summaries)

            # Group papers by category
            categories = {}
            for paper in all_today_papers:
                cat = self._categorize(paper)
                categories.setdefault(cat, []).append(paper)

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# Research Papers Compilation - {datetime.now().strftime('%B %d, %Y')}\n\n")
                f.write("## Summary\n")
                f.write(f"This compilation contains {len(all_today_papers)} new papers in biorobotics research.\n\n")

                for cat, plist in categories.items():
                    f.write(f"## {cat} ({len(plist)} papers)\n\n")
                    for paper in plist:
                        f.write(f"### {paper['title']}\n")
                        f.write(f"**Authors:** {'; '.join(paper.get('authors', []))}\n")
                        f.write(f"**DOI:** {paper.get('doi', '')}\n")
                        f.write(f"**TRL:** {paper.get('trl', 1)}\n")
                        f.write(f"**Keywords:** {', '.join(paper.get('keywords', []))}\n")
                        f.write(f"**Summary:** {paper.get('summary', '')}\n")
                        if paper.get('pdf_url'):
                            f.write(f"**PDF:** {paper['pdf_url']}\n")
                        f.write("---\n\n")

            logger.info(f"Created archive file: {filename} ({len(all_today_papers)} papers)")
            return filename
        except Exception as e:
            logger.error(f"Failed to create archive file: {str(e)}")
            return None

    def _generate_rss_feed(self, papers, output_path="docs/feed.xml", max_items=50):
        """Generate an RSS 2.0 feed of the most recent papers."""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            site_url = "https://firmanserdana.github.io/research-assistant-paper-compiler/"
            feed_url = f"{site_url.rstrip('/')}/feed.xml"
            build_date = email.utils.formatdate(usegmt=True)

            items_xml = []
            for paper in papers[:max_items]:
                title = html.escape(paper.get('title', 'Untitled Paper'))
                doi = paper.get('doi', '')
                link = f"https://doi.org/{doi}" if doi else site_url
                guid = link
                category = html.escape(paper.get('category', 'General Biorobotics'))
                authors = html.escape('; '.join(paper.get('authors', [])))
                summary = html.escape(paper.get('summary', ''))
                trl = paper.get('trl', 1)
                pdf_url = paper.get('pdf_url', '')

                archive_date = paper.get('archive_date', '')
                pub_date = build_date
                if archive_date:
                    try:
                        dt = datetime.strptime(archive_date, '%Y-%m-%d')
                        pub_date = dt.strftime('%a, %d %b %Y 00:00:00 GMT')
                    except Exception:
                        pass

                description_parts = [
                    f"<p><strong>Authors:</strong> {authors}</p>",
                    f"<p><strong>Category:</strong> {category} | <strong>TRL:</strong> {trl}</p>"
                ]
                if summary:
                    description_parts.append(f"<p><strong>Summary:</strong> {summary}</p>")
                if doi:
                    description_parts.append(f"<p><strong>DOI:</strong> <a href=\"https://doi.org/{doi}\">{doi}</a></p>")
                if pdf_url:
                    description_parts.append(f"<p><strong>PDF:</strong> <a href=\"{pdf_url}\">Open Access PDF</a></p>")

                desc_cdata = f"<![CDATA[{''.join(description_parts)}]]>"

                item_xml = f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{guid}</guid>
      <pubDate>{pub_date}</pubDate>
      <category>{category}</category>
      <description>{desc_cdata}</description>
    </item>"""
                items_xml.append(item_xml)

            rss_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Biorobotics Literature Monitor</title>
    <link>{site_url}</link>
    <description>Automated academic literature tracking, verification, and web portal compilation for biorobotics, neural decoding, and neuroprosthetics research.</description>
    <language>en-us</language>
    <lastBuildDate>{build_date}</lastBuildDate>
    <atom:link href="{feed_url}" rel="self" type="application/rss+xml"/>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(rss_content)

            logger.info(f"Generated RSS feed at {output_path} with {len(items_xml)} items")
            return output_path
        except Exception as e:
            logger.error(f"Failed to generate RSS feed: {e}")
            return None

    def _load_scholarly_cache(self, cache_path="scholarly_metadata_cache.json"):
        """Load cached OpenAlex / Crossref bibliometric metadata (pub_year, venue, citations, oa_url)."""
        cache = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load scholarly metadata cache: {e}")

        runtime_cache = getattr(self, "_runtime_scholarly_cache", {})
        if runtime_cache:
            updated = False
            for k, v in runtime_cache.items():
                if k not in cache:
                    cache[k] = v
                    updated = True
            if updated and not getattr(self, "dry_run", True) and cache_path == "scholarly_metadata_cache.json":
                try:
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2)
                except Exception as e:
                    logger.warning(f"Failed to update scholarly metadata cache: {e}")
        return cache

    def _extract_modalities(self, paper):
        """
        Classify a paper into up to 3 structured study modality and subject tags
        based on its title, summary, and keywords.
        """
        title_l = (paper.get("title") or "").lower()
        sum_l = (paper.get("summary") or "").lower()
        kw_l = " ".join(paper.get("keywords") or []).lower()
        text = f"{title_l} {sum_l} {kw_l}"

        tags = []

        # 1. Subject / Study Design
        if any(w in title_l for w in ("review", "survey", "meta-analysis", "overview", "perspective")):
            tags.append("Review / Survey")
        elif any(w in text for w in ("tetraplegi", "paraplegi", "amputee", "spinal cord injur", "sci patient", "human participant", "patients with", "clinical trial", "in humans", "prosthesis user")):
            tags.append("Human / Clinical")
        elif any(w in text for w in ("macaque", "monkey", "non-human primate", "rhesus")):
            tags.append("Non-Human Primate")
        elif any(w in text for w in ("rat", "rodent", "mouse", "porcine", "animal model", "in vivo")):
            tags.append("Preclinical / In Vivo")

        # 2. Neural Interface Modality
        if any(w in text for w in ("intracortical", "motor cortex", "microelectrode array", "cortical decoding", "ecog", "electrocorticograph", "brain-computer", "brain–computer")):
            tags.append("Intracortical / Brain")
        elif any(w in text for w in ("surface emg", "semg", "hd-emg", "high-density electromyography", "electromyograph", "myoelectric", "motor unit")):
            tags.append("Surface / HD-sEMG")
        elif any(w in text for w in ("peripheral nerve", "intraneural", "intrafascicular", "cuff electrode", "regenerative peripheral", "nerve stimulation", "neurostimulation")):
            tags.append("Peripheral Nerve")
        elif any(w in text for w in ("epidural electrical", "spinal cord stimulation", "transcutaneous spinal", "spinal cord–computer")):
            tags.append("Spinal Stimulation")

        # 3. Engineering / Algorithmic Focus
        if any(w in text for w in ("sensory feedback", "tactile", "biomimetic", "bidirectional", "artificial sensation")):
            tags.append("Closed-Loop Sensory")
        elif any(w in text for w in ("exoskeleton", "soft robot", "robotic glove", "orthos", "gait training", "wearable robot")):
            tags.append("Exoskeleton / Soft Robot")
        elif any(w in text for w in ("prosthetic hand", "bionic hand", "hand prosthesis", "neuroprosthe")):
            tags.append("Bionic / Prosthetic Hand")
        elif any(w in text for w in ("deep learning", "convolutional", "lstm", "recurrent neural", "transformer", "kalman", "neural network")):
            tags.append("Deep Learning / AI")

        if not tags:
            tags.append("Neural Engineering")

        return tags[:3]

    def _compute_related_papers(self, unique_papers, top_k=3):
        """
        Precompute the top-K most related papers in the corpus for each paper
        using weighted title/keyword token overlap, category match, and shared modalities.
        """
        stop = {
            'the', 'a', 'an', 'of', 'in', 'on', 'for', 'and', 'to', 'with', 'by', 'from',
            'at', 'using', 'via', 'based', 'study', 'analysis', 'after', 'during', 'control',
            'research', 'patients', 'hand', 'finger', 'decoding', 'spinal', 'cord', 'injured'
        }

        paper_tokens = []
        for p in unique_papers:
            raw = f"{p.get('title', '')} {' '.join(p.get('keywords') or [])} {(p.get('summary') or '')[:200]}".lower()
            words = {w for w in re.findall(r'[a-z0-9]{3,}', raw) if w not in stop}
            paper_tokens.append(words)

        for i, p1 in enumerate(unique_papers):
            scores = []
            t1 = paper_tokens[i]
            m1 = set(p1.get('modalities') or [])
            c1 = p1.get('category', '')
            for j, p2 in enumerate(unique_papers):
                if i == j:
                    continue
                t2 = paper_tokens[j]
                union_len = len(t1 | t2)
                jaccard = (len(t1 & t2) / union_len) if union_len else 0.0
                cat_bonus = 0.12 if c1 and c1 == p2.get('category', '') else 0.0
                mod_bonus = 0.08 * len(m1 & set(p2.get('modalities') or []))
                total_score = jaccard + cat_bonus + mod_bonus
                if total_score > 0.05:
                    scores.append((total_score, p2))

            scores.sort(key=lambda x: (x[0], int(x[1].get('citations') or 0)), reverse=True)
            p1['related_papers'] = [
                {
                    'title': item.get('title', ''),
                    'doi': item.get('doi', ''),
                    'pub_year': item.get('pub_year') or (item.get('archive_date') or '2025')[:4],
                    'venue': item.get('venue', ''),
                    'trl': item.get('trl', 1)
                }
                for _, item in scores[:top_k]
            ]

    def _write_github_step_summary(self, new_papers, unique_papers, categories_map, analytics):
        """Write a Markdown execution summary to $GITHUB_STEP_SUMMARY when running in GitHub Actions."""
        summary_path = os.getenv("GITHUB_STEP_SUMMARY")
        if not summary_path:
            return
        try:
            lines = [
                "## 🤖 Biorobotics Literature Monitor — Run Summary\n",
                f"- **Total Verified Papers in Portal**: **{len(unique_papers)}**",
                f"- **Newly Discovered Papers This Run**: **{len(new_papers)}**",
                f"- **Total Corpus Citations (OpenAlex)**: **{analytics.get('total_citations', 0):,}**",
                f"- **Open Access PDF Coverage**: **{analytics.get('oa_count', 0)} / {len(unique_papers)} papers**\n",
                "### 📊 Category Breakdown\n",
                "| Research Category | Papers |",
                "| :--- | :---: |",
            ]
            for cat, cnt in sorted(categories_map.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"| {cat} | {cnt} |")

            if new_papers:
                lines.append("\n### 🆕 Newly Added Papers\n")
                lines.append("| Title | DOI | Category | TRL |")
                lines.append("| :--- | :--- | :--- | :---: |")
                for p in new_papers:
                    d = p.get('doi', '')
                    lines.append(f"| {p.get('title', '')} | [`{d}`](https://doi.org/{d}) | {p.get('category', '')} | TRL {p.get('trl', 1)} |")

            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            logger.warning(f"Could not write GITHUB_STEP_SUMMARY: {e}")

    def _send_webhook_notification(self, new_papers):
        """Send an optional Slack or Discord webhook alert when new papers are discovered."""
        if not new_papers:
            return
        webhook_url = os.getenv("SLACK_WEBHOOK_URL") or os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return
        try:
            bullet_lines = [
                f"• *{p.get('title', 'Untitled')}* (TRL {p.get('trl', 1)}) — https://doi.org/{p.get('doi', '')}"
                for p in new_papers[:10]
            ]
            text = (
                f"🤖 *Biorobotics Literature Monitor*: Discovered *{len(new_papers)}* new verified paper(s):\n"
                + "\n".join(bullet_lines)
            )
            payload = {"content": text} if "discord" in webhook_url.lower() else {"text": text}
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            logger.warning(f"Webhook notification failed: {e}")

    def generate_site(self, new_papers, output_dir='docs'):
        """Generate the HTML site, update.json, and RSS feed with all papers."""
        try:
            os.makedirs(output_dir, exist_ok=True)
            scholarly_cache = self._load_scholarly_cache()

            historical_papers = self.load_papers_from_archives()
            all_papers = new_papers + historical_papers

            # Deduplicate papers based on DOI (case-insensitive) and merge metadata across archives
            papers_by_doi = {}
            for paper in all_papers:
                doi = self._normalize_doi(paper.get('doi', ''))
                if not doi:
                    continue
                doi_key = doi.lower()
                if doi_key not in papers_by_doi:
                    merged = dict(paper)
                    merged['doi'] = doi
                    merged['category'] = self._categorize(merged)
                    papers_by_doi[doi_key] = merged
                else:
                    existing = papers_by_doi[doi_key]
                    # Keep highest TRL across digests
                    existing['trl'] = max(int(existing.get('trl') or 1), int(paper.get('trl') or 1))
                    # Keep most recent archive_date
                    if (paper.get('archive_date') or '') > (existing.get('archive_date') or ''):
                        existing['archive_date'] = paper['archive_date']
                    # Prefer non-filler technical summary
                    ex_sum = existing.get('summary') or ''
                    new_sum = paper.get('summary') or ''
                    if (not ex_sum or ex_sum.startswith('Recent research in ')) and new_sum and not new_sum.startswith('Recent research in '):
                        existing['summary'] = new_sum
                    elif new_sum and not new_sum.startswith('Recent research in ') and not ex_sum.startswith('Summary for ') and len(new_sum) > len(ex_sum) + 40:
                        existing['summary'] = new_sum
                    # Preserve Open Access PDF link if present
                    if not existing.get('pdf_url') and paper.get('pdf_url'):
                        existing['pdf_url'] = paper['pdf_url']
                    # Merge unique keywords (up to 8)
                    ex_kw = list(existing.get('keywords') or [])
                    seen_kw = {k.lower() for k in ex_kw if isinstance(k, str)}
                    for kw in (paper.get('keywords') or []):
                        if isinstance(kw, str) and kw.lower() not in seen_kw and len(ex_kw) < 8:
                            ex_kw.append(kw)
                            seen_kw.add(kw.lower())
                    existing['keywords'] = ex_kw

            unique_papers = list(papers_by_doi.values())

            # Enrich every unique paper with OpenAlex/Crossref bibliometrics, evidence TRL, and study modalities
            trl_buckets = {"basic": 0, "prototype": 0, "clinical": 0}
            modality_counts = {}
            venue_counts = {}
            total_citations = 0
            oa_count = 0

            for p in unique_papers:
                doi_key = p['doi'].lower()
                meta = scholarly_cache.get(doi_key, {})

                # Enrich publication year, venue, citations, and Open Access PDF
                fallback_year = (p.get('archive_date') or '2025')[:4]
                if doi_key.startswith('10.1101/202'):
                    fallback_year = doi_key.split('/')[1][:4]
                p['pub_year'] = meta.get('pub_year') or p.get('pub_year') or fallback_year
                p['venue'] = meta.get('venue') or p.get('venue') or ('bioRxiv' if doi_key.startswith('10.1101/') else '')
                p['citations'] = int(meta.get('citations') if meta.get('citations') is not None else (p.get('citations') or 0))
                if not p.get('pdf_url') and meta.get('oa_url'):
                    p['pdf_url'] = meta['oa_url']

                # Upgrade generic fallback TRL (1 or 2) using clinical/engineering evidence
                raw_trl = int(p.get('trl') or 1)
                if raw_trl <= 2:
                    p['trl'] = self._estimate_trl(p.get('title', ''), p.get('summary', ''), p.get('keywords'), current_trl=raw_trl)
                else:
                    p['trl'] = raw_trl

                # Extract structured study modalities
                p['modalities'] = self._extract_modalities(p)

                # Aggregate analytics metrics
                trl_val = int(p['trl'])
                if trl_val >= 7:
                    trl_buckets["clinical"] += 1
                elif trl_val >= 4:
                    trl_buckets["prototype"] += 1
                else:
                    trl_buckets["basic"] += 1

                for mod in p['modalities']:
                    modality_counts[mod] = modality_counts.get(mod, 0) + 1
                if p['venue']:
                    venue_counts[p['venue']] = venue_counts.get(p['venue'], 0) + 1
                total_citations += p['citations']
                if p.get('pdf_url'):
                    oa_count += 1

            # Compute top-3 related papers per card
            self._compute_related_papers(unique_papers, top_k=3)

            # Sort papers: newest archive date first, then publication year, then title
            unique_papers.sort(
                key=lambda p: (p.get('archive_date', '0000-00-00'), str(p.get('pub_year', '0000')), p.get('title', '')),
                reverse=True
            )

            # Compute category counts
            categories_map = {}
            for p in unique_papers:
                cat = p.get('category', 'General Biorobotics')
                categories_map[cat] = categories_map.get(cat, 0) + 1

            top_venues = sorted(venue_counts.items(), key=lambda x: x[1], reverse=True)[:8]
            sorted_modalities = sorted(modality_counts.items(), key=lambda x: x[1], reverse=True)

            analytics = {
                "trl_buckets": trl_buckets,
                "modalities": sorted_modalities,
                "top_venues": top_venues,
                "total_citations": total_citations,
                "oa_count": oa_count,
            }

            # Render template
            template = self.template_env.get_template('index.html')
            html_content = template.render(
                papers=unique_papers,
                categories=categories_map,
                analytics=analytics,
                updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                count=len(new_papers),
                total=len(unique_papers)
            )

            index_path = os.path.join(output_dir, 'index.html')
            update_path = os.path.join(output_dir, 'update.json')
            rss_path = os.path.join(output_dir, 'feed.xml')

            with open(index_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Write update.json
            with open(update_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "new_count": len(new_papers),
                    "total_count": len(unique_papers),
                    "total_citations": total_citations,
                    "oa_count": oa_count,
                    "categories": categories_map,
                    "trl_buckets": trl_buckets
                }, f, indent=2)

            # Generate RSS feed
            self._generate_rss_feed(unique_papers, output_path=rss_path)

            # Emit GitHub Actions Job Summary if running in CI
            if output_dir == 'docs':
                self._write_github_step_summary(new_papers, unique_papers, categories_map, analytics)

            logger.info(f"Generated site with {len(new_papers)} new papers and {len(unique_papers)} total papers")
            return len(unique_papers)
        except Exception as e:
            logger.error(f"Failed to generate site: {str(e)}")
            raise

    def execute(self):
        """Execute the complete literature monitoring process."""
        if getattr(self, 'generate_site_only', False):
            logger.info("Executing site regeneration only...")
            self.generate_site([])
            return []

        new_papers = []

        try:
            # Build set of existing DOIs to prevent duplicates
            existing_dois = set()
            if self.zot:
                try:
                    existing_items = self.zot.everything(self.zot.items())
                    for item in existing_items:
                        item_doi = self._normalize_doi(item.get('data', {}).get('DOI', ''))
                        if item_doi:
                            existing_dois.add(item_doi.lower())
                except Exception as e:
                    logger.warning(f"Could not fetch Zotero items: {e}")

            for p in self.load_papers_from_archives():
                p_doi = self._normalize_doi(p.get('doi', ''))
                if p_doi:
                    existing_dois.add(p_doi.lower())

            # Query papers for all search terms (serialize arXiv requests to respect 1-req/3s rate limit)
            if self.provider == "arxiv":
                results = []
                for idx, term in enumerate(self.search_terms):
                    if idx > 0:
                        time.sleep(2.5)
                    results.append(self._deep_research_query(term))
            else:
                with ThreadPoolExecutor(max_workers=3) as executor:
                    results = list(executor.map(self._deep_research_query, self.search_terms))

            # If include_arxiv requested alongside another provider, query sequentially
            if self.include_arxiv and self.provider != "arxiv":
                for idx, term in enumerate(self.search_terms):
                    if idx > 0:
                        time.sleep(2.5)
                    results.append((term, self._arxiv_search(term, max_results=self.limit or 5)))

            for term, response_text in results:
                if not response_text:
                    continue

                parsed_papers = self._parse_response(response_text)
                if not parsed_papers and self.provider not in ("openalex", "crossref", "arxiv"):
                    logger.warning(f"No verified papers from {self.provider} for '{term}'; falling back to OpenAlex.")
                    fallback_text = self._openalex_search(term, rows=self.limit or 10)
                    parsed_papers = self._parse_response(fallback_text) if fallback_text else []

                if self.limit:
                    parsed_papers = parsed_papers[:self.limit]

                for paper in parsed_papers:
                    paper_doi = paper.get('doi', '').lower()
                    if paper_doi and paper_doi not in existing_dois:
                        paper['source_term'] = term
                        paper['category'] = self._format_category_name(term)
                        paper['summary'] = self._generate_paper_summary(paper)

                        if not self.dry_run:
                            self._save_to_zotero(paper)
                        new_papers.append(paper)
                        existing_dois.add(paper_doi)

            if self.dry_run:
                logger.info(f"[DRY RUN] Discovered {len(new_papers)} new papers. Skipping archive writing and Zotero sync.")
                return new_papers

            if new_papers:
                self._create_archive_file(new_papers)
                self.generate_site(new_papers)
                self._send_webhook_notification(new_papers)
                logger.info(f"Successfully added and compiled {len(new_papers)} new papers.")
            else:
                logger.info("No new papers found in this run.")
                self.generate_site([])

            return new_papers

        except Exception as e:
            logger.error(f"Execution error: {str(e)}")
            raise


def parse_args():
    parser = argparse.ArgumentParser(description="Biorobotics Literature Monitor & Paper Compiler")
    parser.add_argument(
        "--provider", "-p",
        choices=["auto", "crossref", "arxiv", "openalex", "perplexity", "gemini", "anthropic", "openai", "ollama"],
        default="auto",
        help="Scholarly data source or AI provider (default: auto)"
    )
    parser.add_argument("--model", "-m", help="AI model override (e.g. sonar-pro, gemini-2.5-flash)")
    parser.add_argument("--term", "-t", action="append", help="Specific search term to query (can be specified multiple times)")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Maximum number of papers per search term")
    parser.add_argument("--dry-run", action="store_true", help="Run search without writing archive files or syncing to Zotero")
    parser.add_argument("--skip-zotero", action="store_true", help="Skip Zotero syncing even if credentials exist")
    parser.add_argument("--include-arxiv", action="store_true", help="Query arXiv in addition to primary provider")
    parser.add_argument("--generate-site-only", action="store_true", help="Regenerate website, update.json, and RSS feed from existing archives without searching")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    monitor = LiteratureMonitor(
        model=args.model,
        provider=args.provider,
        dry_run=args.dry_run,
        limit=args.limit,
        skip_zotero=args.skip_zotero,
        include_arxiv=args.include_arxiv,
    )
    if args.term:
        monitor.search_terms = args.term
    if args.generate_site_only:
        monitor.generate_site_only = True
    monitor.execute()
