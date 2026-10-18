# Rankstien Crochet / AdSense Vertical — v0.1

**Status:** isolated, research/QA-only. **No site provisioned or published.** This is an implementation artifact, not proof of live traffic or pattern testing.

## Why this is a separate publishing vertical

The existing Rankstien campaign contract is based on Spanish food (Recipe JSON-LD, ingredients, food-image generation, and a fixed 15-source/30-remaster Pinterest flow). Crochet is **not** a cooking Recipe vertical. Reusing that pipeline unchanged would publish the wrong structured data, generate unverified stitch sequences and risk using unrelated/unauthorized source photographs.

The new vertical is designed for free original crochet patterns and instructional pages funded by display advertising. US English is the initial language/market assumption, subject to further GSC/Pinterest data. The website and Pinterest brand identities must be completely separate from RecetaDolce and RecetaGenial.

## Implemented in this phase

- `rankstein/crochet_vertical.py`: crochet-only keyword classification with clear long-tail informational intent, commercially mixed search blocking, sourced volume handling and **no fabricated keyword difficulty**.
- `rankstein/crochet_vertical.py`: prepublication evidence audit for pattern rows, stitch arithmetic, testers, license provenance, US/UK terminology, image rights and nonfood structured-data guards.
- `rankstein/cli.py`: `crochet research` and `crochet audit` commands. Both are read-only with respect to production DBs/accounts; the research command writes **only a local JSON report**.
- `rankstein/niche_detector.py`: correct craft-category fallback rather than recipe categories.
- Focused unit tests isolate behavior from existing recipe domains.

## Run against the 87-keyword research CSV

Download the accompanying `crochet_keyword_research_2026-10-18.csv` research pack to your Rankstien machine. Then:

```shell
python rankstein.py crochet research --csv path/to/crochet_keyword_research_2026-10-18.csv --output data/reports/crochet-keyword-review.json
python rankstein.py crochet audit --input docs/examples/crochet-untested-pattern.json
python -m pytest tests/unit/test_crochet_vertical.py -q
```

The CSV preserves third-party estimates as *third-party, market-unspecified numbers*. Unmeasured keywords have `null` volume and keyword difficulty. This tool neither fetches fresh Pinterest/GSC data nor authorizes publication; publishing remains disabled until full independent live research and site/pattern QA gates are implemented.

## Launch architecture (next phases)

1. **Original premium brand and independent site:** Create separate Next.js app and Vercel project, own Supabase project/bucket and domain, own brand assets, new public URL namespace. Do **not** clone the RecetaDolce food template. Define taxonomy: free bags; beginner tutorials; stitches; blankets/home; accessories; flowers/amigurumi; seasonal projects. Premium editorial design, responsive original photos, typography, structured interactive pattern renderer, printable ad-light craft directions.
2. **Crochet editorial content contract:** Separate `Pattern`, `Tutorial`, `StitchGuide` and `Roundup` types. Pattern carries test swatch, gauge, hook size, yarn weight, row/stitch arithmetic, actual finished dimensions, US/UK abbreviation glossary, verified photographer/license, explicit human physical-testing attestation and review identity. Roundups cite and link to authorized original patterns; never scrape/repost their paid or free instructions. Editors must verify factual claims.
3. **SEO pipeline:** topic and page-type mapping, intent clustering, duplicate/cannibalization controls, ranking evidence with market/time/source fields, search console sync and incremental search-indexing QA. Treat broad head terms as hubs, not automatically selected pattern targets. Reject copycat patterns, unsupported safety claims and synthetic performance numbers.
4. **Pinterest engine:** craft-specific photo/pin templates; 2:3 originals, multiple genuine angles and close-ups, source licensing, destination/intent/slug validation, appropriate pin boards and per-account rate budgets. No recycled competitor photos or watermark removal. Optional visual experiments only from media we own/license.
5. **Ad-first architecture:** sensible page depth, scrollable tutorial navigation, accessible sticky table of contents, anchored sections, stable reserved ad placements, ad density and Core Web Vitals budgets. No forced PDF download, paywall or misleading clickbait.
6. **Full production admission:** only after original tester checks, mobile/desktop browser QA, data isolation, published website QA, authorized ad and Pinterest accounts, non-placeholder hero photos, and measured live CWV. Start with *zero* automated pattern publication; gradually enable only verified types. Record proof per article/pin.

## Traffic strategy

- **Launch focus:** free crochet bags, bag strap durability, lining, moss/waistcoat stitch tutorials, stitch-count/terminology charts and beginner techniques.
- **Phase 2:** blankets, small accessories, flowers, and seasonal decorations as editorial capacity permits.
- **Ads:** prioritize Google and Pinterest *outbound* traffic, engaged article views and eventual actual page RPM, never invented monthly traffic figures.
- **Metrics:** track evidence source and market, keyword intent, indexability, GSC clicks/impressions/CTR, Pinterest outbound clicks, engaged pageviews, LCP/INP/CLS p75 and measured display-ad RPM.

## Explicit safe boundaries

- No domain chosen or purchased; no Pinterest account/board connected for the new vertical; no new Supabase/Vercel project yet.
- No domain manifest generated for the active production registry, so food workers cannot accidentally publish crochet as recipes.
- Never apply the current `rankstein add-domain --clone-site` food-template path to crochet.
- No original pattern may be described as `tested` just because its row/stitch counts add up. Independent hands-on crocheting is required; automation verifies the evidence contract, not physical feasibility.
- The first version of the premium site should ship with a small set of genuine guides and photographs, not an automatically populated mass-content library.

## Acceptance for phase two

- Independent responsive website app and 360/390/768/1024/1440 pixel QA.
- Draft/approval/physical-tested workflow for pattern posts with clear state and audit history.
- Real rights-verified images, unique brand and accounts and zero recipe-schema contamination.
- GSC and Pinterest data not faked; ad placements reserved without ad overlays causing CLS.
- Do not enable auto-publication until safety and content-quality test suites are green.
