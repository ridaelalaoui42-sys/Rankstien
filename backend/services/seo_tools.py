"""RankStein — SEO Tools Service
Keyword density, readability, meta tags, heading structure, content scoring.
"""

from __future__ import annotations

import re


def calculate_keyword_density(text: str, keyword: str) -> float:
    """Calculate keyword density as percentage."""
    words = text.lower().split()
    kw_words = keyword.lower().split()
    if not words or not kw_words:
        return 0.0
    count = 0
    kw_len = len(kw_words)
    for i in range(len(words) - kw_len + 1):
        if words[i : i + kw_len] == kw_words:
            count += 1
    return round((count * kw_len / len(words)) * 100, 2) if words else 0.0


def calculate_readability_score(text: str) -> float:
    """Flesch Reading Ease score."""
    sentences = re.split(r"[.!?]+", text)
    words = text.split()
    syllables = sum(_count_syllables(w) for w in words)
    num_sentences = max(len(sentences), 1)
    num_words = max(len(words), 1)
    score = 206.835 - 1.015 * (num_words / num_sentences) - 84.6 * (syllables / num_words)
    return round(max(0, min(100, score)), 1)


def _count_syllables(word: str) -> int:
    """Approximate syllable count for a word."""
    word = word.lower().strip(".,!?;:'\"")
    if len(word) <= 2:
        return 1
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e"):
        count -= 1
    return max(1, count)


def generate_meta_title(keyword: str, brand: str = "") -> str:
    """Generate SEO-optimized title tag (max 60 chars)."""
    title = f"{keyword.title()}"
    if brand:
        title += f" | {brand}"
    return title[:60]


def generate_meta_description(content: str, keyword: str) -> str:
    """Generate meta description (max 155 chars)."""
    sentences = re.split(r"[.!?]+", content)
    desc = ""
    for s in sentences:
        s = s.strip()
        if len(s) > 20 and keyword.lower() in s.lower():
            desc = s
            break
    if not desc and sentences:
        desc = sentences[0].strip()
    if len(desc) > 155:
        desc = desc[:152] + "..."
    return desc


def analyze_heading_structure(html_or_text: str) -> dict:
    """Analyze heading hierarchy."""
    import re

    h1 = re.findall(r"<h1[^>]*>(.*?)</h1>", html_or_text, re.IGNORECASE | re.DOTALL)
    h2 = re.findall(r"<h2[^>]*>(.*?)</h2>", html_or_text, re.IGNORECASE | re.DOTALL)
    h3 = re.findall(r"<h3[^>]*>(.*?)</h3>", html_or_text, re.IGNORECASE | re.DOTALL)
    issues = []
    if len(h1) == 0:
        issues.append("Missing H1 tag")
    elif len(h1) > 1:
        issues.append(f"Multiple H1 tags ({len(h1)} found)")
    if len(h2) == 0:
        issues.append("No H2 tags found")
    if len(h3) > 0 and len(h2) == 0:
        issues.append("H3 tags without H2 parent")
    return {
        "h1_count": len(h1),
        "h2_count": len(h2),
        "h3_count": len(h3),
        "issues": issues,
        "valid": len(issues) == 0,
    }


def check_internal_linking(content: str, domain: str) -> dict:
    """Analyze internal linking structure."""
    import re

    links = re.findall(r'href="([^"]*)"', content)
    internal = [l for l in links if domain in l or l.startswith("/")]
    external = [l for l in links if l.startswith("http") and domain not in l]
    return {
        "internal_count": len(internal),
        "external_count": len(external),
        "total_links": len(links),
        "internal_ratio": round(len(internal) / max(len(links), 1) * 100, 1),
    }


def calculate_content_score(content: str, keyword: str, niche: str = "General") -> dict:
    """Overall SEO content score 0-100."""
    word_count = len(content.split())
    density = calculate_keyword_density(content, keyword)
    readability = calculate_readability_score(content)
    headings = analyze_heading_structure(content)
    score = 0
    if 1500 <= word_count <= 4000:
        score += 30
    elif 800 <= word_count < 1500:
        score += 20
    elif word_count >= 4000:
        score += 25
    if 0.5 <= density <= 2.5:
        score += 25
    elif 0.1 <= density < 0.5:
        score += 15
    score += min(20, readability / 5)
    if headings.get("valid"):
        score += 15
    elif headings.get("h1_count", 0) >= 1:
        score += 10
    score += 10 if word_count > 1000 else 5
    return {
        "overall_score": min(100, round(score)),
        "word_count": word_count,
        "keyword_density": density,
        "readability": readability,
        "heading_structure": headings,
    }
