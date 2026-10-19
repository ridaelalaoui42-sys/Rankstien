# Stitch Atlas — Illustrated Academy Scale Blueprint
**Research/design proposal, 19 October 2026.** Inventory entries below are not generated, tested, or published assets.

## North star
Free, original illustrated crochet education with visible skill progress; searchable, helpful editor-reviewed companion guides generate search/Pinterest discovery. The academy is the primary UX and never pretends that quiz completion certifies physical crochet skill.

## Target inventory
- **12 worlds × 6 units × 4 lessons = 288 core lessons**, plus **36 applied labs** = **324 experiences**.
- **Five graded, explanation-based question types per experience** = **1,620 planned questions**, each reviewed for correctness, clarity and accessibility.
- **Four instructional visuals per experience** = **1,296**; plus **12 world covers + 36 badges + 120 diagnostics + 36 capstone illustrations** = **1,500 proposed original visual assets**.

## The twelve learning worlds

| World | Skill focus | Core lessons | Applied labs |
|---|---|---:|---:|
| 01. First Loop | Start without the overwhelm | 24 | 3 |
| 02. Stitch Alphabet | Decode the moves, one loop at a time | 24 | 3 |
| 03. Fabric Detective | Learn to see what the stitches tell you | 24 | 3 |
| 04. Rows & Edges | Make smooth lines and reliable repeats | 24 | 3 |
| 05. Rounds & Shapes | Geometry that grows beautifully | 24 | 3 |
| 06. Texture Lab | Build a vocabulary of beautiful surfaces | 24 | 3 |
| 07. Yarn & Gauge Lab | Understand fiber, measurements and fit | 24 | 3 |
| 08. Color & Motifs | Make small pieces into expressive design | 24 | 3 |
| 09. Bag Maker Studio | From beautiful swatches to practical structure | 24 | 3 |
| 10. Blankets & Home | Make larger work manageable | 24 | 3 |
| 11. Amigurumi & 3D Thinking | Practice volume, shaping and responsible finishing | 24 | 3 |
| 12. Designer Atelier | Read, critique and design with evidence | 24 | 3 |

## Content and art-production contract

1. Each lesson has a primary learning objective, a genuine worked explanation, terminology flag (US/UK), five reviewed questions, an accessible text equivalent and four purposeful visuals.
2. The four visual roles **vary by lesson**: technique uses motion/loop anatomy, tools use object callouts/comparison/decision trees, stitch math uses accurate annotated measurement, and safety uses evidence and limitations. Specialized labs use task, workflow, diagnostic and assessment visuals.
3. Technical hook/yarn-path diagrams: render from a validated geometric stitch grammar to SVG, not unconstrained AI. For complex manipulations require real photos or crocheter-reviewed hand-drawn source diagrams.
4. Aesthetic editorial scenes, path covers, badges and Pinterest compositions: may use illustration-model generation, but check arms/hands, stitch geometry, captions, originality, and license provenance.
5. Layer image source metadata and transformations: unique asset ID, usage rights, visual alt/caption, skill mapping, reviewer ID, version, status, checksum, export formats, audit trail.
6. Production sequence: topic brief → standards sources → skill outline → 4 visual specifications → render variants → geometric checks → crochet expert review → copy/accessibility review → responsive preview → approve → publish.
7. Never publish or describe untested real-world patterns, wearable fit, stitch counts, toys or load-bearing straps as tested merely because image generation or a code check succeeded.

## Platform architecture changes required

- Replace hard-coded `academy.mjs` paths/quizzes/badges with independently versioned structured curriculum files (worlds, units, lessons, quizzes, media, prerequisites). Immutable stable IDs prevent lost progress on updates.
- Introduce a skill graph: what each lesson teaches, assumes, tests, and the correct next micro-lesson for the learner. Permit free skipping; prerequisites inform recommendations, not a paywall.
- Migrate `stitch-atlas.academy.progress.v1` to version 2 with read-only backup, migration tests, per-question remediation, best score and eventual offline export/import. Browser storage stays temporary until a dedicated account/database exists.
- Render SVG stitch diagrams with deterministic reusable stitches, loops, yarn paths, layers, callouts, color-safe contrasts, 1x/2x exports and no inaccessible hidden interactions.
- Separate canonical SEO guide pages from quiz/checkpoint pages; guide gets unique search-intent focus, lesson provides interactive microlearning, neither mass-produces thin SEO landing pages.
- Implement build-time schema validation, perceptual duplicate detection, orphan-link checks, image integrity, quiz answer consistency, alt text, broken media and route checks.
- Add dedicated Rankstien production queue and inspection UI: `research → briefing → drafting → art → fact/check → physical sign-off if relevant → staging → publish → monitor`.
- Website keeps preview `noindex`; deployment, domain and isolated Supabase are later decisions. No changes to RecetaGenial/RecetaDolce.

## Rollout gates and milestones

| Release | Lessons/labs in total | Visual assets target | Priority |
|---|---:|---:|---|
| Pilot / proof of visual grammar | 24 | 120 | World 1, usable quiz+illustration QA |
| Foundations launch | 72 | 360 | Worlds 1–3, learnable sequence, true beginner results |
| Intermediate expansion | 192 | 960 | Worlds 4–8; stitch precision and realistic sample verification |
| Full academy v1 | 324 | 1,500 | Worlds 9–12 plus project labs, original skill-based comparisons |

## Staffing / QA

- Curriculum editor/instructional designer (sequencing, exercises and feedback).
- Expert crocheter/tester (terminology, physical movements, swatches, stitch geometry, fit/safety).
- Visual designer (illustration templates and art direction) plus a small automated SVG/pin export pipeline.
- Full-stack developer (content registry, Next.js routes, persistence, analytics and QA).
- SEO editor (unique search intent, image optimization and publishing calendar). One person may cover multiple roles, but the actual physical crochet verification cannot be automated away.

## Costs and guardrails

- Do not pre-authorize unlimited spending; establish explicit caps for image API, experts, compute, storage and photography.
- Illustrative non-vendor quote examples: 1,500 visuals × $0.05/$0.25/$1.00 **effective cost per final approved asset** = $75/$375/$1,500, excluding retries, expert labor, photos and platform subscriptions. These are scenario variables, NOT current tool prices or a complete project quote.
- A test batch measures realistic approved-per-generation yield, revision rate and review hours before we commit to a budget; true instructor-tested quality, not raw GPU output, is the main expense.
- Approval gates: correct yarn path, terminology standard, five nontrivial reviewed questions, accurate captions/alt, mobile accessibility, copy originality, citations, image licensing, no fabricated physical testing.

## SEO / ads design

- Google explicitly warns about scaled low-value content: 324 genuinely different skills and visual teaching artifacts are valuable only if users learn something new; do not publish 324 near-identical keyword pages.
- Canonical tutorial pages support Google and Google Images via descriptive filenames, semantic `<img>` elements, responsive image sizes, caption/alt, sitemap; quizzes do not need to be separate search landing pages.
- Monetization belongs alongside useful substantive editorial sections, not covering the answer buttons, progress cards or navigation. Avoid ads on under-construction and low-content quiz-only screens.

## Evidence references

- Craft Yarn Council crochet chart symbols: https://craftyarncouncil.com/standards/crochet-chart-symbols
- Craft Yarn Council skill levels and yarn standards: https://craftyarncouncil.com/standards/project-levels ; https://media.craftyarncouncil.com/standards/yarn-weight-system
- Google image indexing: https://developers.google.com/search/docs/appearance/google-images
- Google generated-content guidance: https://developers.google.com/search/docs/fundamentals/using-gen-ai-content
- Google publisher policies: https://support.google.com/adsense/answer/10502938

**Safety:** Everything in this blueprint is proposal-stage until a real instructor and release check approve it. No new spend, domain or DB provisioned.
