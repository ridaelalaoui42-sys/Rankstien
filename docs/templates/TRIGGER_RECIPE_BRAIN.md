# Recipe Agency Brain - Trigger Template

**Language**: Spanish (español)  
**Audience**: Spanish speakers (Spain, Mexico, Latin America)

Copy and paste this, fill in the brackets, and send to trigger the full system.

---

## TRIGGER COMMAND

```
ACTIVATE_RECIPE_BRAIN

KEYWORD: [RECIPE KEYWORD HERE]
VARIATIONS: [OPTIONAL - dietary, cooking methods, seasonal angle]
STYLE: [OPTIONAL - tone & visual direction]
CLIENT_SITE: [OPTIONAL - which blog to publish to, or "demo"]
```

### Example Trigger (Spanish):

```
ACTIVATE_RECIPE_BRAIN

KEYWORD: salmón al horno con verduras en 30 minutos
VARIATIONS: sin gluten, rápida para entre semana, saludable
STYLE: cocina mediterránea moderna, fotografía cálida de cocina
CLIENT_SITE: demo
```

### Otro Ejemplo:

```
ACTIVATE_RECIPE_BRAIN

KEYWORD: paella fácil para la familia
VARIATIONS: con pollo, con mariscos, receta tradicional simplificada
STYLE: comida en familia, calor y tradición, cocina española auténtica
CLIENT_SITE: demo
```

---

## What the Brain Does (in order):

1. **Analyzes the keyword** for SEO opportunity (search volume, competition, gaps)
2. **Generates a full blog article** (1500-2000 words, SEO-optimized)
3. **Creates Pinterest pin design brief** (ready for visual rendering)
4. **Produces all metadata** (schema, tags, distribution plan)
5. **Saves all outputs** to your workspace folder

---

## Output Folder Structure

After execution, you'll find:

```
[PROJECT_ROOT]/output/ (was C:\Users\REDX420\.gemini\)
├── articles/
│   └── article_[keyword-slug].md
├── pinterest/
│   └── pin_[keyword-slug].md
├── metadata/
│   └── metadata_[keyword-slug].md
└── publish_logs/
    └── [keyword-slug]_checklist.txt
```

---

## Tips for Best Results

- **Keyword**: Specific + niche (not just "pasta", try "no-boil baked ziti with spinach")
- **Variations**: List 2-3 real angles your audience searches for
- **Style**: Describe the final blog's voice and aesthetic
- **Client Site**: Name it or say "demo" to generate without linking to a specific site yet

---

## Spanish Recipe Keywords to Test

Ready to go? Try one of these:

1. **"pollo al ajillo fácil"** — clásico español, popular, variaciones (sin gluten, rápido)
2. **"gazpacho frío para el verano"** — receta de temporada, refrescante, típico español
3. **"empanadas rellenas para principiantes"** — comida familiar, enseñanza clara, compartible
4. **"tacos al pastor caseros"** — tendencia latam, técnica clara, compartible en redes
5. **"receta de mole rojo tradicional"** — auténtico, festivo, regional mexicano

---

**To activate now**, copy the trigger template above, fill in the bracketed fields, and send it.

The brain will execute and produce everything you need to publish.
# Template Update - 2026-05-10

When using this trigger, assume the current RankStein runtime: Gemini CLI subscription/OAuth, AgentMemory, daily trend intelligence, CLI-only subscriber administration, and validated Pinterest account handles. Do not include service credentials, Supabase keys, Gemini auth tokens, browser session paths, or Pinterest session data in generated prompts or Markdown output.

Image and pin briefs must follow `docs/templates/IMAGE_GENERATION_CONTRACT.md`: realistic recipe visuals, explicit aspect ratios, negative prompts, Spanish alt text, no embedded URLs, and short overlay concepts only.

---
