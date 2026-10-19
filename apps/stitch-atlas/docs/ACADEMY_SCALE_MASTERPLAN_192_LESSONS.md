# Stitch Atlas Academy — Scale Blueprint
**Dated 2026-10-19 | Planning artifact, not an implementation or publication claim**

## Executive decision
Make Stitch Atlas an illustrated, interactive crochet learning platform with an SEO-first library surrounding it. Academy lessons teach; long-form guides answer search queries; original, physically validated patterns form capstones. No fees or subscriptions are required.

## Actual platform baseline (confirmed)
- Stack: existing Next.js 15.5.28 / React 19.1.10 app in `apps/stitch-atlas`, Vercel staging; noindex until domain, content, policies and quality gates are ready.
- 3 existing learning paths, 12 lesson checkpoints with three questions each, 6 badges, progress in browser localStorage V1.
- 12 illustrated reference guides and 12 Pinterest draft images; current Academy build and Playwright CI were passing at the time of planning.
- `academy.mjs` stores paths/quizzes/achievements as hand-written arrays; progress is keyed by lesson ID and points are calculated from completion, so redesign schema before inserting 180 extra lessons.
- Existing recipe blogs and databases should remain isolated. Avoid subscriptions or external accounts at this stage.

## Definitive curriculum map (target, not produced)
16 pathways x 6 levels x 2 lessons = **96 levels, 192 lessons**. Each lesson gets **five independently reviewed instructional visuals**. Total **960 diagrams**, plus 16 path covers, 48 achievements, and a proposed 192 Pinterest creatives. Accompany with at least 120 in-depth, independently useful long-form guides (not duplicate academy pages).

| No. | World / skill pathway | Stage | Levels | Lessons | Diagrams |
|---:|---|---|---:|---:|---:|
| 01 | Tools, Yarn & the Maker’s Setup | foundation | 6 | 12 | 60 |
| 02 | First Loops & Foundational Movements | foundation | 6 | 12 | 60 |
| 03 | Rows, Stitch Counts & Smooth Edges | foundation | 6 | 12 | 60 |
| 04 | Pattern Language & Diagram Literacy | foundation | 6 | 12 | 60 |
| 05 | The Stitch Library | technique | 6 | 12 | 60 |
| 06 | Increases, Decreases & Stitch Math | technique | 6 | 12 | 60 |
| 07 | Working in Rounds & Circles | technique | 6 | 12 | 60 |
| 08 | Texture, Gauge & Fabric Behavior | technique | 6 | 12 | 60 |
| 09 | Granny Squares & Modular Crochet | project | 6 | 12 | 60 |
| 10 | Colorwork, Stripes & Motifs | project | 6 | 12 | 60 |
| 11 | The Structural Crochet Bag Lab | project | 6 | 12 | 60 |
| 12 | Blankets, Borders & Home Textiles | project | 6 | 12 | 60 |
| 13 | Amigurumi & Sculptural Crochet | mastery | 6 | 12 | 60 |
| 14 | Wearables, Fit & Sizing | mastery | 6 | 12 | 60 |
| 15 | Lace, Specialty Fibers & Advanced Charts | mastery | 6 | 12 | 60 |
| 16 | Design Studio & Pattern Verification | mastery | 6 | 12 | 60 |

## Lesson template: ten minutes that actually teach
1. **Visual hook:** close-up craft illustration showing the common mistake or key technique.
2. **Learning target:** one concise measurable crochet skill.
3. **Explain:** original instructor-reviewed prose, terminology and appropriate materials.
4. **Show:** 3–5 semantic vector diagrams with hover labels and useful alt text.
5. **Try:** accessible interactive task, such as count the stitches, put steps in order, diagnose an edge, match stitch symbols, or predict row count.
6. **Retrieve:** four-item question pool with evidence-based explanations; show one question at a time.
7. **Reflect:** optional off-screen physical practice, never auto-awarded as independently tested mastery.
8. **Review later:** spaced-practice prompt derived from quiz history; no forced login.
9. **Related reading:** substantive SEO guide and the prior/next lesson; avoid cannibalizing identical topics.
10. **Evidence gate:** independent crochet specialist approves all illustrated stitch placement and claims before public indexing.

## Illustrated asset system (avoid 1,000 unrelated AI generations)
- Build a **semantic SVG stitch grammar**: loops, tops, posts, chain-space marks, yarn-over, hook, hand markers, turning chains, row indices, arrows, count highlights, increases/decreases, and fabric-facing metadata.
- Define an **illustration storyboard** per lesson with stitch type, yarn order, exact step states, viewpoint, instructor reference photos, and all diagram alt text.
- Generate SVG deterministically from validated stitch semantics and design tokens; use the same geometry engine for animated highlights and drag/tap hotspots.
- Use image generation for editorial still-life, yarn palettes, nontechnical cover art, classroom ambience and Pinterest compositions; never assume a rendered AI hand/stitch close-up is technically accurate.
- Produce five pedagogical SVGs per lesson: concept, anatomy, process-A, process-B and common mistake. Reuse stitch primitives, **not** duplicated lesson content.
- Store assets with immutable IDs, skill references, source rights, dimensions, theme variables, text alternatives, last-reviewed date, crop variants and tested status.
- Export optimized SVG for site and 1000x1500 raster Pinterest design as a separate deliverable after reviewing and verifying target URLs.
- Technical accuracy threshold: zero wrong loops, incorrect stitch counts, false unsupported load/safety claims, misleading hands or mislabeled US/UK abbreviations. Fail closed on doubt.

## Engineering architecture
**Content as code until DB:** `academy/worlds/*.json`, `academy/lessons/*.mdx` with validated frontmatter and diagram manifests, `academy/assessments/*.json`, `academy/assets/*.json`. Build-time validation enforces referential integrity, unique slugs, valid quiz answers, real SVG paths and craft review state. Git review works without Supabase.
**Runtime renderer:** route `/academy`, `/academy/world/[id]`, `/academy/level/[id]`, `/academy/lesson/[id]`; keep legacy links redirecting or mapped. Use a versioned generic `LessonRenderer`, `ExerciseRenderer` and `DiagramViewer`, not one hard-coded React component for each page.
**Quiz engines:** single/multi-select, match terminology, tap diagram hotspot + keyboard list fallback, count visible loops, drag/order steps + keyboard move-up/down alternative, read symbol charts, troubleshoot mistakes, calculate stitch changes, and compare fabric properties.
**Progress:** version 2 migration from localStorage V1; use IndexedDB for structured progress with JSON export/import, idempotent XP events keyed by content/version/attempt, daily review queue, conflict-free migrations and no paid/monetary awards. No cross-device sync until independent DB is connected.
**Image pipeline:** vector technique components + Figma/Illustrator review + static SVG export + `sharp` raster/AVIF/WebP + Playwright screenshot assertions; keep original human-validated source for regenerations.
**Monetization:** academy and active exercise surfaces ad-free (or at minimum avoid any ads near answer controls). Display ads primarily on editorial guides, pattern reference pages and non-interactive pages after approval. Never award points for ad views/clicks.
**SEO:** one primary canonical guide per search intent with detailed learning text, diagrams and useful FAQs; academy screens point to it. Index only unique substantive routes when the real domain and policies are ready. Retain stage-wide noindex now.
**Observability:** anonymous aggregate events only after consent/privacy assessment; measure visit-to-lesson, first correct, hint usage, completion, seven-day return, diagram comprehension errors, organic clicks and Pinterest outbound clicks.

## Human quality gates
1. Technical instructor supplies a reference swatch/photo or validated chart and lesson goal.
2. Editorial writer constructs unique instructions and explanation, no verbatim copyrighted commercial patterns.
3. Illustrator builds step diagrams from this reference; never uses random image generations to determine stitch physics.
4. Second person independently checks diagrams and expected quiz answers.
5. Accessibility audit: WCAG 2.2 keyboard nav, screen-reader alternatives, no timed penalizing tasks; test drag exercises with button-based alternatives.
6. Tooling checks: SVG safe attributes, browser at 360/390/768/1024/1440, no hydration warnings, no fake schema/rating/tester/URL/rights.
7. Only tested physical **original object patterns** can be claimed tested; educational charts can be published with instructor review but must not present safety/load certifications.

## Pilot before scale
- Phase 0 (2–3 weeks): vector grammar prototype for chain, single crochet, double crochet, increase/decrease, two reliable interactive exercise engines and one accessible diagram viewer. Have crochet instructor review every screenshot.
- Phase 1 (weeks 4–8): **24 deeply validated lessons, 120 diagrams, 12+ guides, 24 Pin drafts**, full assessment/progress engine; run observational tests with real beginner crocheters.
- Phase 2 (months 3–5): reach 72 lessons and 360 diagrams; tune comprehension, UX and production velocity before scaling.
- Phase 3 (months 6–9): reach 144 lessons and 720 diagrams when publishing QA capacity is stable.
- Phase 4 (months 10–12+): reach 192 lessons and 960 diagrams, 120 canonical guides, 192 pins; expand only when expertise/validation throughput supports it.

## Budget scenarios (planning estimates, not provider quotes)
| Program scope | Illustration specs | Possible external production allowance (USD) | Status |
|---|---:|---:|---|
| Pilot: 24 reviewed lessons | 120 | $2,000–$10,000 | Estimate, excludes salaried internal work |
| Medium: 96 reviewed lessons | 480 | $15,000–$50,000 | Estimate, depends on vector reuse and expert-review rate |
| Full: 192 reviewed lessons | 960 | $40,000–$140,000+ | Estimate, quality-focused multi-month team |
API render pricing is a secondary line item: vector diagrams should be deterministic; AI editorial generations billed by quality/tokens and may require many revisions. Budget separately for craft instructor time, illustrator labor, editing, photography/video, accessibility, engineering, QA, storage and usage. No purchases are authorized by this file.

## Staffing / dependencies
- Crochet instructor + independent external reviewer (two people for rigorous craft validation).
- Editorial curriculum designer with a strong beginner-teaching focus.
- Senior front-end engineer comfortable with Next.js, SVG/Canvas interactions, accessibility and visual regression.
- Vector illustrator/art director defining a consistent stitch language and reusable components.
- SEO/editorial lead for canonical pages and Google Search Console intent mapping.
- Part-time QA/accessibility and still-life photographer/real crochet hand demonstration as needed.

## Launch and traffic measurement
- **Leading indicators:** 24/72/144/192 validated lessons, quiz accuracy after explanation, quiz retry improvement, completed visual task rate, error discovery frequency, instructor QA queue age, media rights completeness, first meaningful render.
- **SEO metrics:** GSC non-brand impressions, clicks, indexed canonical guide ratio, image-search and Pinterest outbound clicks, topically relevant internal-link flows. No invented monthly searches.
- **Business metrics:** return sessions, engaged reading pageviews, actual post-approval page RPM, revenue per organic reader, user satisfaction. Measure before forecasting.
- **Guardrails:** noindex until launch, no auto-submitted unreviewed pattern, no rewards for ads, no cloned copyrighted charts, no API plan upgrades without approval.

## Risks and decision gates
- Biggest risk: stitch diagrams look beautiful but mis-teach. The instructor-reviewed SVG grammar is the gating requirement.
- Scaling low-value micro-pages could trigger Google scaled-content abuse concerns; do not manufacture hundreds of nearly duplicate search pages.
- Learners could play quizzes without physically practicing: badges are entertainment/progress indicators, not formal competence claims.
- User progress only exists in browser until a dedicated backend is authorized; expose export/import early.
- Evaluate three sample lessons with beginners, instructor correction and accessibility testing before authorizing full production expenditure.

## Supporting official sources
- Craft Yarn Council crochet symbol standards: https://craftyarncouncil.com/standards/crochet-chart-symbols
- Craft Yarn Council project levels: https://www.craftyarncouncil.com/standards/project-levels
- Google Search people-first content: https://developers.google.com/search/docs/fundamentals/creating-helpful-content
- Google scaled-content spam: https://developers.google.com/search/docs/essentials/spam-policies
- Google AdSense placement rules: https://support.google.com/adsense/answer/1346295
- Spaced learning review: https://doi.org/10.1038/s44159-022-00089-1
- OpenAI GPT Image 2.5 cost model: https://developers.openai.com/api/docs/guides/image-generation