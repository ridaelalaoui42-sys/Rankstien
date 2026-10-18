# Stitch Atlas: the free crochet learning library

**Phase:** staging only · **Model:** free editorial content → organic Google/Pinterest discovery → potential future display ads. No paid patterns, invented reviews, borrowed imagery or untested original projects.

## What was built

Six original, factual, researched craft-learning articles, deliberately different from new original patterns. Each has a visually distinct, original 1200 × 720 explanatory SVG, a separate 1000 × 1500 Pinterest-ready *concept* PNG, a short answer, a practice/checklist, coherent reading sections, real craft references, sensible related articles, mobile layouts and a printable mode. All articles remain `noindex` while the site has no verified official domain. No ads, analytics, fictional maker testimonials or fake tester identities.

| URL | Search intent | Supporting internal links | Trust and content QA |
|---|---|---|---|
| `/guides/how-to-count-crochet-stitches` | Why stitch totals change, row-edge counting | US/UK glossary, gauge, moss stitch | Separates stitch top from turning-chain assumptions; cites CYC |
| `/guides/us-uk-crochet-terms` | US and UK abbreviation conversion | Stitch counting, moss stitch, gauge | References Craft Yarn Council equivalencies, no invented rich results |
| `/guides/how-to-measure-crochet-gauge` | How to measure a swatch in the center | Bag yarn, stitch counting, conversion | Swatch examples labeled as arithmetic, not tested pattern specs |
| `/guides/how-to-choose-yarn-for-crochet-bags` | Selecting firm bag fabric and strap materials | Lining, gauge, counting | Does not promise “never stretches” or universal weights |
| `/guides/how-to-line-a-crochet-bag` | Measuring a handmade bag lining | Bag yarn, gauge, stitch counting | Explains trial fitting; not described as universal tested pattern |
| `/guides/moss-stitch-crochet-explained` | How chain spaces create moss-stitch texture | Stitch counting, US/UK terms, gauge | Conceptual grid clearly marked “not a pattern chart” |

Keyword volumes and organic difficulty are **not measured by these articles**, and the article count does not predict search traffic. Refer to the earlier 87-keyword CSV for unverified third-party/provisional research. Additional articles should be added only after first-party evidence and genuine editorial checking.

## Design system / visual assets

- Brand: Stitch Atlas original illustrated wordmark / mark / warm cream, sage and terracotta; retained exactly from premium site PR.
- Cards: tactile paper background, serif editorial headlines, unobtrusive category labels, generous typography hierarchy, accessible links and responsive illustrations.
- Rich reader: hero illustration, short answer, section table of contents, checklist, source citations, related guides, local save link and clear print stylesheet.
- Illustrations: six original self-contained SVG diagrams, not copies of established crochet symbol charts and not misleadingly presented as real swatch photographs.
- Pins: six native 1000 × 1500 PNGs at `public/pins/`, each intended to represent a **learning reference**, not a completed tested pattern. Only branded original artwork; never copy competitor product photos.
- The pin manifest at `docs/PINTEREST_ASSETS_MANIFEST.json` intentionally has `destinationHost: null`, `approvedToPublish:false` and `autopublish:false`. Do not queue Pins without verified official domain and destination-HTTP checks.

## Rankstien integration contract

Rankstien's existing crochet handoff exports **research-only** keyword candidates; the offline studio stores **unpublished** article concepts locally. These six editorial guide assets are code-reviewed static pages, not automatic publishing from that draft queue. There is no API path that converts a CSV candidate into an indexable article without a separate source and editorial review. Do not reuse any food Recipe JSON-LD.

## AdSense/SEO gates for the eventual domain

1. Pick and verify a real craft brand domain. Check naming/IP before launch; no `example.com` substitutes in public canonical URLs or markup.
2. Add real publisher/about/contact/privacy disclosures and a supported analytics/consent stack for the actual audience. Do not claim AdSense approval before receiving it.
3. Independently review original technical content for accuracy, accessibility and rights (diagrams are original). Replace/contribute with real tested, fully owned finished-object photos for any future *pattern* posts.
4. Verify page rendering, responsive layout and zero broken internal links. Run accessibility inspection and page performance audits on the final domain.
5. Set `NEXT_PUBLIC_SITE_URL` to the verified canonical `https://…` domain. Lift the global preview `noindex` and `robots.txt` block **only in a separately reviewed launch PR**. The guarded Article JSON-LD remains disabled unless indexing is explicitly enabled. Confirm unique title/description, canonical, sitemap, image rights, and structured-data accuracy on every released page.
6. Claim Search Console and Pinterest verified website; measure **real** GSC impressions/clicks, Pinterest **outbound** clicks, qualified sessions, pageviews and actual ad RPM; don't attribute invented search volumes or estimated rankings to individual tutorials.
7. Reserve ad slots rather than inserting ads before approval; keep reading content and tools accessible and avoid cumulative layout shift.

## Editorial release rule

Free explanatory guides can be authored without pretending they are newly tested crochet patterns. A new original finished-object pattern needs actual tester/row-count/rights evidence and real project photos. No unaudited AI-generated stitch instructions should be converted into published patterns by a background agent.
