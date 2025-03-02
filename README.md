# Biorobotics Literature Monitor

Automated academic paper tracking system for PhD researchers in biorobotics.

## Configuration

1. **Secrets Setup** (GitHub → Settings → Secrets):
   - `PPLX_API_KEY`: Perplexity API key (or any LLM API key you have)
   - `ZOTERO_LIB_ID`: Zotero user/library ID
   - `ZOTERO_API_KEY`: Zotero API keyß
   - `ANTHROPIC_API_KEY`: Anthropic key (optional)

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
- Cross-source verification
- Weekly updates can be seen on gh page https://firmanserdana.github.io/research-assistant-paper-compiler/
