# GENERIC Pinterest Pin Design Template
## For Any Spanish Recipe Keyword

**Use this template for every recipe keyword in your autonomous system.**

Replace `{{RECIPE_NAME}}` with your keyword, and auto-generate complete Pinterest pin briefs.

Current RankStein rule: this template is subordinate to `docs/templates/IMAGE_GENERATION_CONTRACT.md`. Keep destination URLs, domain handles, and Pinterest account handles in the pin payload metadata; do not render them into the image. Prefer short overlay concepts over model-rendered long text.

---

## TEMPLATE INSTRUCTIONS

**When triggered with a keyword**, follow this process:

### STEP 1: AUTO-OPTIMIZE TITLE

**Input**: `{{RECIPE_NAME}}` (raw keyword)

**Process**:
1. Detect the language (in Spanish already? Keep as is)
2. Translate to natural Spanish if needed
3. Upgrade wording to sound premium, emotional, viral-worthy
4. Keep it short and mouthwatering
5. Add benefit/descriptor (fácil, delicioso, cremoso, etc.)

**Output Example**:
- Input: "pollo al ajillo"
- Output: "Pollo al Ajillo: Cremosidad y Sabor Español"

---

## STEP 2: GENERIC VISUAL CONCEPT

### TOP BANNER (200px)

**Background**:
- Vintage parchment texture (aged, slightly burned edges)
- Warm beige tones with subtle grain (#E8DCC8)
- Decorative elements based on recipe:
  - {{AUTO_GENERATE_ICON_1}} (ingredient-specific icon, top left)
  - {{AUTO_GENERATE_ICON_2}} (cooking method icon, top right)
  - Thin decorative line separator
  - Subtle floral ornaments in corners

**Typography - Main Title**:
- **Text**: {{RECIPE_NAME_OPTIMIZED}}
- **Font**: Elegant serif (Playfair Display, Georgia, etc.)
- **Size**: 72px (bold)
- **Color**: {{AUTO_COLOR_BURGUNDY}} or {{AUTO_COLOR_DARK_BROWN}}
- **Position**: Centered, top 60% of banner
- **Letter Spacing**: +2px (luxury feel)

**Typography - Subtitle**:
- **Text**: {{AUTO_GENERATE_EMOTIONAL_SUBTITLE}}
  - Examples: "Receta Fácil y Deliciosa", "Irresistiblemente Cremoso", "Tradición en Tu Mesa"
- **Font**: Handwritten script (Dancing Script, Pacifico)
- **Size**: 36px (italic)
- **Color**: {{AUTO_COLOR_WARM_BROWN}} (#704214)
- **Position**: Below main title

**Attribution**:
- **Text**: "www.tublog.com"
- **Font**: Small sans-serif (Montserrat, 14px)
- **Color**: {{AUTO_COLOR_MEDIUM_BROWN}} (#996B47)
- **Position**: Bottom right

---

### CENTER IMAGE (800px)

**Food Photography Brief** - {{AUTO_GENERATE_DESCRIPTION}}:

**Dish Presentation**:
- **Main subject**: {{AUTO_DESCRIBE_PLATING}}
  - Example for pollo: "Golden, glossy chicken thighs with garlic sauce in a rustic ceramic bowl"
  - Example for pasta: "Creamy pasta with visible sauce coating, freshly grated cheese on top"
  - Example for ice cream: "Creamy ice cream in glass bowl with garnish on top"
- **Texture showcase**: {{AUTO_IDENTIFY_KEY_TEXTURES}}
  - Identify primary textures (creamy, glossy, golden, crispy, etc.)
  - Show them clearly in photo
  - Add relevant garnishes
- **Garnish**: {{AUTO_SUGGEST_GARNISH}} (fresh herb, ingredient, sauce drizzle)

**Scene Styling**:
- **Surface**: {{AUTO_SURFACE_TYPE}} (Usually rustic dark wooden table)
- **Props** (1-2 complementary):
  - {{AUTO_SUGGEST_PROP_1}} (e.g., ingredient bowl, utensil, cloth)
  - {{AUTO_SUGGEST_PROP_2}} (e.g., glass of drink, fresh ingredient, cooking tool)
- **Cloth**: Linen or patterned kitchen cloth (color: {{AUTO_SUGGEST_CLOTH_COLOR}})
- **Optional accents**: Small ingredient pile, spice jar, fresh herbs

**Lighting Setup**:
- **Type**: Warm, soft natural light (golden hour preferred)
- **Direction**: Side-lighting, 45° angle
- **Depth of Field**: Shallow (f/2-f/4) — food sharp, background soft
- **Shadows**: Soft shadows, no harsh lines
- **Color Temperature**: Warm (3500-4000K), slightly orange-tinted
- **Mood**: {{AUTO_MOOD}} (cozy, indulgent, intimate, warm, inviting)

**Composition**:
- **Positioning**: Centered or slightly left (rule of thirds)
- **Framing**: Close-up, main dish fills 60% of frame
- **Angle**: Slightly top-down (30° angle), showing texture + garnish
- **Background**: Blurred (wooden table + cloth + props)

---

### BOTTOM SECTION: RECIPE CARD (500px)

**Layout**: 2-Column Design

```
┌──────────────────┬──────────────────┐
│  INGREDIENTES    │  PASOS           │
│  (Auto-Generated)│  (Auto-Generated)│
├──────────────────┼──────────────────┤
│ {{INGREDIENTS}}  │ {{STEPS}}        │
└──────────────────┴──────────────────┘
```

**Background**:
- **Color**: Cream white (#FFF8F0)
- **Texture**: Subtle grain overlay
- **Border**: Thin decorative line (warm brown, 2px)
- **Padding**: 20px margins

### LEFT COLUMN: "INGREDIENTES"

**Header**:
- **Text**: "Ingredientes"
- **Font**: Bold serif (same as title)
- **Size**: 28px
- **Color**: {{AUTO_COLOR_BURGUNDY}} (#8B1538)
- **Icon**: {{AUTO_INGREDIENT_ICON}} (small relevant icon)

**Ingredients List** - {{AUTO_GENERATE_INGREDIENTS}}:
```
{{AUTO_INGREDIENT_1}} {{AUTO_QTY_1}}
{{AUTO_INGREDIENT_2}} {{AUTO_QTY_2}}
{{AUTO_INGREDIENT_3}} {{AUTO_QTY_3}}
{{AUTO_INGREDIENT_4}} {{AUTO_QTY_4}}
{{AUTO_INGREDIENT_5}} {{AUTO_QTY_5}}
(Additional as needed)
```

**Formatting**:
- **Font**: Clean sans-serif (Open Sans, 16px)
- **Color**: {{AUTO_COLOR_WARM_BROWN}} (#704214)
- **Line height**: 1.8 (spacious)
- **Bullet style**: Small illustrated icons or circles
- **Visual elements**: Small icons next to 3-4 key ingredients

### RIGHT COLUMN: "PASOS"

**Header**:
- **Text**: "Pasos"
- **Font**: Bold serif
- **Size**: 28px
- **Color**: {{AUTO_COLOR_BURGUNDY}} (#8B1538)
- **Icon**: {{AUTO_STEP_ICON}} (clock, timer, or cook icon)

**Steps** - {{AUTO_GENERATE_STEPS}} (3-5 steps):
```
1️⃣ {{AUTO_STEP_1}}
   {{AUTO_SUBSTEP_1}}

2️⃣ {{AUTO_STEP_2}}
   {{AUTO_SUBSTEP_2}}

3️⃣ {{AUTO_STEP_3}}
   {{AUTO_SUBSTEP_3}}

[4️⃣ {{AUTO_STEP_4}} if needed]
[5️⃣ {{AUTO_STEP_5}} if needed]
```

**Formatting**:
- **Font**: Clean sans-serif (Open Sans, 15px)
- **Color**: {{AUTO_COLOR_WARM_BROWN}} (#704214)
- **Line height**: 1.7
- **Number style**: Emoji numbers (1️⃣ 2️⃣ 3️⃣ 4️⃣)
- **Icons**: Small cooking action icons (stir, chop, heat, etc.)

---

## STEP 3: FOOTER (50px)

**Main CTA**:
- **Text**: {{AUTO_GENERATE_EMOTIONAL_CTA}}
  - Examples: "¡Irresistible!", "¡Delicioso!", "¡Cremosidad Pura!", "¡A Pruébalo!"
- **Font**: Handwritten script (32px, italic)
- **Color**: {{AUTO_COLOR_BURGUNDY}} (#8B1538)
- **Position**: Centered

**Decorative Elements**:
- Heart icons (❤️) on both sides
- Small food-related icons below

---

## COLOR PALETTE AUTO-GENERATION

**Base Colors** (consistent):
- Deep Burgundy: #8B1538 (titles)
- Warm Brown: #704214 (body text)
- Cream: #FFF8F0 (card background)
- Parchment: #E8DCC8 (banner background)
- Medium Brown: #996B47 (accents)

**Recipe-Specific Accent Colors** {{AUTO_GENERATE}}:
- **For seafood**: Blues + teals + grays
- **For chocolate/coffee**: Dark browns + golds
- **For fruits/berries**: Reds + pinks + warm tones
- **For pasta/bread**: Golds + warm oranges
- **For soup/stew**: Warm earth tones + reds
- **For vegetables**: Greens + earth tones
- **For dairy**: Creams + soft golds

---

## TYPOGRAPHY AUTO-SELECTION

| Element | Font Family | Size | Weight | Color |
|---------|-------------|------|--------|-------|
| Main Title | {{AUTO_SERIF}} | 72px | Bold | {{AUTO_TITLE_COLOR}} |
| Subtitle | {{AUTO_SCRIPT}} | 36px | Regular | {{AUTO_SUBTITLE_COLOR}} |
| Section Headers | {{AUTO_SERIF}} | 28px | Bold | {{AUTO_HEADER_COLOR}} |
| Body Text | {{AUTO_SANS}} | 16px | Regular | {{AUTO_BODY_COLOR}} |
| Small Text | {{AUTO_SANS}} | 12-14px | Regular | {{AUTO_SMALL_COLOR}} |
| CTA | {{AUTO_SCRIPT}} | 32px | Italic | {{AUTO_CTA_COLOR}} |

**Auto-Selection Rules**:
- Serif fonts for premium/traditional recipes
- Script fonts for desserts/elegant dishes
- Sans-serif for clean, modern feeling

---

## NEGATIVE PROMPT (Consistent for All)

```
blurry, low quality, flat lighting, bad typography, distorted text, 
unrealistic food, messy layout, modern minimal UI, 
amateur design, pixelated, compressed image, 
harsh shadows, oversaturated colors, 
cluttered composition, illegible text, 
plastic-looking food, fake garnish, 
poor contrast, burnt edges, 
modern sans-serif only, 
low resolution, stock photo feel
```

---

## OUTPUT SPECIFICATION

**For Each Keyword, Generate**:

1. **Optimized Title** (premium, emotional, Spanish)
2. **Food Photo Brief** (specific to recipe type)
3. **Scene Styling** (props, surface, cloth color)
4. **Complete Ingredients List** (metric units, realistic quantities)
5. **Complete Steps** (3-5 clear, concise steps)
6. **Emotional CTA** (Spanish phrase)
7. **Color Palette** (recipe-specific accent colors)
8. **Typography Selections** (specific fonts)
9. **Icon Suggestions** (ingredient + step icons)

---

## AUTOMATED WORKFLOW

### When Keyword Triggered:

```
INPUT: {{RECIPE_NAME}} (e.g., "pollo al ajillo fácil")

PROCESS:
├─ Step 1: Auto-optimize title
├─ Step 2: Auto-generate food brief
├─ Step 3: Auto-suggest props + styling
├─ Step 4: Auto-generate ingredients
├─ Step 5: Auto-generate steps
├─ Step 6: Auto-select colors
├─ Step 7: Auto-select typography
├─ Step 8: Auto-suggest icons
└─ Step 9: Output complete design brief

OUTPUT: Production-ready Pinterest pin design (ready for AI or designer)
```

---

## USAGE EXAMPLES

### Example 1: Pollo al Ajillo Fácil

```
INPUT: pollo al ajillo fácil

AUTO-GENERATED:
- Title: "Pollo al Ajillo: Cremosidad y Sabor Español"
- Mood: Cozy, indulgent, warm
- Colors: Burgundy + warm brown + golden tones
- Props: Garlic bulb, rustic bowl, linen cloth
- Ingredients: 1kg pollo, 8 dientes ajo, 200ml AOVE, 100ml vino blanco...
- Steps: Cortar pollo | Dorar en aceite | Añadir ajo | Cocinar lentamente | Servir
- CTA: "¡Irresistiblemente Cremoso!"
```

### Example 2: Helado de Fresas

```
INPUT: helado de fresas con crema

AUTO-GENERATED:
- Title: "Helado de Fresas: Cremosidad Pura"
- Mood: Indulgent, refreshing, cozy
- Colors: Strawberry red + cream + warm golds
- Props: Fresh strawberries, whipped cream, vintage spoon
- Ingredients: 500g fresas, 200ml crema, 150ml leche condensada...
- Steps: Lavar fresas | Mezclar | Congelar | Servir
- CTA: "¡Deliciosamente Cremoso!"
```

### Example 3: Tortilla Española

```
INPUT: tortilla española receta

AUTO-GENERATED:
- Title: "Tortilla Española: Receta Auténtica"
- Mood: Warm, traditional, family-friendly
- Colors: Golden brown + cream + earth tones
- Props: Potatoes, onion, wooden spatula, cast iron pan
- Ingredients: 1kg papas, 200ml AOVE, 4 huevos...
- Steps: Cortar papas | Freír | Mezclar huevos | Cocinar | Voltear
- CTA: "¡Tradición en Tu Mesa!"
```

---

## FOR AUTONOMOUS SYSTEM INTEGRATION

**When `ACTIVATE_AUTONOMOUS_SYSTEM` is triggered:**

1. Brain receives keyword
2. Applies this generic template
3. Auto-fills all `{{AUTO_*}}` fields
4. Generates complete Pinterest pin design brief
5. Outputs ready-for-designer specifications

**Result**: Every keyword automatically gets a production-ready Pinterest pin design brief (no manual design work).

---

## IMPLEMENTATION

This template should be **built into your autonomous system** so that:

1. **Keyword input** → Autonomous system applies template
2. **Auto-fills all fields** → No manual decisions
3. **Generates complete brief** → Ready for Midjourney/Canva/Designer
4. **Outputs specifications** → Production-ready

**Each keyword = Automatic Pinterest pin brief (complete, detailed, ready to execute)**

---

## Ready?

This template is now part of your autonomous system.

**Next time you trigger**:
```
ACTIVATE_AUTONOMOUS_SYSTEM
KEYWORD: tu_receta_favorita
```

**System will automatically**:
✅ Generate optimized title  
✅ Create food photo brief  
✅ Suggest props + styling  
✅ List ingredients  
✅ Write steps  
✅ Select colors  
✅ Choose typography  
✅ Suggest icons  
✅ Output complete Pinterest pin brief  

**All automatic. All ready for Midjourney/Canva/Designer.**
# Template Update - 2026-05-10

Pinterest pin generation must preserve the destination URL, target domain, and configured account handle. Batch pinning should use only account handles present in the local Pinterest automation configuration and should be validated with `python scripts/dev/validate_automation.py` before large runs.

---
