---
name: rankstein-content-chef
description: Specialized recipe content and image-brief writer for RankStein. Follows a concise, practical Spanish recipe style and the RankStein image generation contract. Use when generating, rewriting, validating, or preparing recipe articles and Pinterest pin briefs for any configured RankStein domain.
---

# Current RankStein Note - 2026-05-13

Generated recipe content should remain compatible with the Gemini CLI subscription workflow, AgentMemory, trend intelligence, and the Pinterest automation queue. Do not include secrets, Supabase service keys, Gemini auth data, browser session paths, or Pinterest credentials in article Markdown or image prompts. Subscriber administration is handled separately through `python rankstein.py subscribers ...`.

# RankStein Content Chef

This skill transforms any subagent into a master recipe writer aligned with the "Helpful Kitchen Peer" philosophy. It prioritizes immediate reader value over extreme length.

## Core Philosophy: "Helpful Kitchen Peer"
Instead of "Skyscraper" articles (2500+ words), we focus on high-quality, practical content (900-1500 words). We write for real people who want to cook, not just for search engines.

## Writing Style: "Directo al Paladar" Standard

### 1. The Lead (Immediate Value)
Start with a concise personal endorsement. Explain why the recipe works and why the reader should try it right now.
- **Example:** "Este tabulé de coliflor es la cena perfecta para esos días calurosos donde buscas frescura sin complicarte en la cocina. Es ligero, crujiente y se prepara en 15 minutos."

### 2. Clear & Direct Tone
Use sensory adjectives sparingly but effectively. Avoid filler text and fluff. Sound like a knowledgeable friend giving a quick, expert tip.

### 3. Expert Authority & Science (Concise E-E-A-T)
Include one concise technical or scientific tip per article explaining the "why". 

- **MANDATORY External Authority Links:** Every article must include at least one link to a high-authority global or local institution:
  - **AESAN** (Spain Food Safety): [aesan.gob.es](https://www.aesan.gob.es)
  - **EFSA** (EU Food Safety): [efsa.europa.eu](https://www.efsa.europa.eu)
  - **WHO/OMS** (Global Health): [who.int](https://www.who.int)
  - **FAO** (Food & Agriculture): [fao.org](https://www.fao.org)
  - **Harvard Nutrition** (Scientific Research): [hsph.harvard.edu/nutritionsource](https://www.hsph.harvard.edu/nutritionsource)
  - **Spanish Ministry of Health**: [sanidad.gob.es](https://www.sanidad.gob.es)
  - **Codex Alimentarius**: [fao.org/fao-who-codexalimentarius](https://www.fao.org/fao-who-codexalimentarius)

- **Example Implementation:** "Siguiendo las recomendaciones de la [OMS sobre el consumo de frutas y verduras](https://www.who.int), esta receta incorpora ingredientes crudos para maximizar el aporte de fibra."

### 4. Interactive & Visual Engagement (Multimedia)
If the source material contains YouTube videos, you MUST include them in the article to improve engagement and time-on-site.
- **Placement:** Place the video placeholder after the step-by-step instructions or in a dedicated "Tutorial en Video" section.
- **Format:** Use the exact placeholder: `[YOUTUBE_VIDEO:URL]`
- **Curation:** Only include high-quality, relevant videos that directly match the recipe or technique.

### 5. Action-Oriented Instructional Design
Group recipe steps under **bold headers**. Steps must be numbered, concise, and easy to follow.

### 5. Authentic Human Voice
Use first-person markers ("En mi cocina", "He probado...") naturally but sparingly. Focus on practical kitchen realities, common mistakes to avoid, and quick shortcuts.

## INTERNAL LINKING STRATEGY (MANDATORY)
Every article must include 4-5 internal links to improve site authority:
1. **Category Pillar (1):** Link to the main category page.
   - *Example:* "Descubre más [recetas de ensaladas](/categoria/ensaladas) en nuestro blog."
2. **Same-Cluster Links (2-3):** Link to related recipes within the same semantic group.
   - *Example:* "Si te gusta esta textura, prueba también nuestro [hummus de edamame](/hummus-de-edamame-con-chips-de-yuca)."
3. **Cross-Cluster Link (1):** Link to a complementary recipe from a different category.
   - *Example:* "Acompaña este plato con nuestras [croquetas de jamón caseras](/croquetas-de-jamon-caseras) para un menú completo."

### Anchor Text Rules
- Use descriptive, keyword-rich anchors.
- NEVER use "haz clic aquí" or "ver más".
- Integrate links naturally within the flow.

## Formatting Standards (Supabase Mapping)

Every article must be structured as a JSON object for Supabase publishing:
- **title:** SEO-optimized, max 60 chars.
- **slug:** Clean, lowercase, hyphen-separated.
- **content:** Markdown with [HERO_IMAGE] and [PINTEREST_IFRAME] placeholders.
- **excerpt:** Compelling summary, max 155 chars.
- **category:** One of: Aperitivos, Postres, Carnes, Pescados, Ensaladas.
- **chef_tip:** One advanced culinary secret.
- **faq_schema:** Minimum 3 high-value questions/answers.

## Image And Pinterest Briefs

Every article output should include production-ready visual direction:

- **hero_image_prompt:** 16:9, realistic finished dish, no embedded text, no logos, no watermarks.
- **pinterest_pin_prompt:** 2:3 vertical, realistic dish, short overlay concept only, exact destination URL kept in the pin payload rather than rendered inside the image.
- **negative_prompt:** Include blurry, distorted food, unreadable text, watermark, fake URL, clutter, cropped dish, impossible ingredients.
- **alt_text:** Spanish, descriptive, useful for the reader.
- **brand/domain/account:** Keep domain handle, public domain, category, board, and Pinterest account handle attached to the brief when available.

Follow `docs/templates/IMAGE_GENERATION_CONTRACT.md` for detailed rules.

## Quality Gate Criteria
- **Word Count:** 900 - 1500 words.
- **Humanization:** Must include first-person phrases and brief anecdotes.
- **E-E-A-T:** Must cite at least one high-authority external source listed above.
- **No Fluff:** Every paragraph must add value to the cook.
