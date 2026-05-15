import re
import logging
from pathlib import Path

logger = logging.getLogger("rankstein.utils")

def normalize_slug(text: str) -> str:
    """
    Normalize a string into a clean URL-friendly slug.
    Example: 'Helado de Vainilla!' -> 'helado-de-vainilla'
    """
    if not text:
        return ""
    # Lowercase and replace non-alphanumeric (except hyphens/underscores) with hyphens
    s = text.lower()
    s = re.sub(r'[^a-z0-9\-_]+', '-', s)
    # Convert underscores to hyphens (standardize on hyphens for slugs)
    s = s.replace('_', '-')
    # Deduplicate hyphens
    s = re.sub(r'-+', '-', s)
    # Strip leading/trailing hyphens
    return s.strip('-')

def extract_slug_from_filename(filename: str) -> str:
    """
    Extract a clean article slug from a Pinterest image filename.
    Handles various naming conventions:
    - luxury_banana-bread_1234567890.jpg
    - remastered_v4_editorial_crepa-nutella_1234567890.png
    - minimal_tacos_hero.webp
    - simple-slug.jpg
    """
    # 1. Strip extension and convert to lower
    stem = Path(filename).stem.lower()
    
    # 2. Remove known branding/layout prefixes
    # Matches: luxury_, remastered_, remastered_v4_, remastered_v4_editorial_, etc.
    stem = re.sub(r"^(luxury|remastered|minimal|minimalist|tutorial|editorial|split|standard)(_v\d+)?(_[a-z]+)?_", "", stem)
    
    # 3. Remove trailing Pinterest IDs (10+ digits)
    stem = re.sub(r"_\d{10,}$", "", stem)
    
    # 4. Remove common suffixes like -hero, -pin, _hero, _pin
    stem = re.sub(r"[_-](hero|pin|og|thumb)$", "", stem)
    
    # 5. Final normalization (convert underscores to hyphens, etc.)
    return normalize_slug(stem)

def get_title_from_slug(slug: str) -> str:
    """Convert a slug back into a Title Case string."""
    return slug.replace("-", " ").replace("_", " ").title()
