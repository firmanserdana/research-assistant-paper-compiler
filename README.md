# Biorobotics Literature Monitor

Automated academic paper tracking system for PhD researchers in biorobotics.

## Configuration

1. **Secrets Setup** (GitHub → Settings → Secrets):
   - `PPLX_API_KEY`: Perplexity API key
   - `ZOTERO_LIB_ID`: Zotero user/library ID
   - `ZOTERO_API_KEY`: Zotero API keyß

2. **Zotero Preparation**:
   - Create collections matching categories:
     - Biohybrid Systems
     - Neuroprosthetics  
     - Soft Robotics
     - General Biorobotics

3. **Customization**:
   - Modify `search_terms` in `search_terms.txt`
   - Adjust quality thresholds in `_validate_paper()`

## Features

- Automatic TRL (Technology Readiness Level) tagging
- ML-powered categorization
- Duplicate prevention
- Daily github pages digest
- Cross-source verification
- Daily updates can be seen on gh page https://firmanserdana.github.io/research-assistant-paper-compiler/
