# Literature Monitor

![Screenshot 2025-08-19 at 22 29 15](https://github.com/user-attachments/assets/a68a529d-9d92-43b9-8a99-68f65523a051)

Automated academic paper tracking system for research.

## Configuration

1. **Secrets Setup** (GitHub → Settings → Secrets):
   - `PPLX_API_KEY`: Perplexity API key (optional). When present, it powers paper discovery and summaries.
   - `ZOTERO_USER_ID` and `ZOTERO_API_KEY`: optional; used to sync discovered papers to Zotero.
   - With no working Perplexity key, discovery automatically uses Crossref's free public API. The site and Markdown archive are still compiled; Zotero sync and AI summaries are skipped.

2. **Zotero Preparation**:
   - Create collections matching categories:
     - Biohybrid Systems
     - Neuroprosthetics  
     - Soft Robotics
     - General Biorobotics

3. **Customization**:
   - Modify `search_terms` in `search_terms.txt`
   - Adjust quality thresholds in `_validate_paper()`
   - Adjust which LLM api you want to use by modifying __init__ args

## Features

- Automatic TRL (Technology Readiness Level) tagging
- ML-powered categorization
- Duplicate prevention
- Cross-source verification
- Weekly updates can be seen on gh page https://firmanserdana.github.io/research-assistant-paper-compiler/
- Archive files as markdown list on /src/archive
