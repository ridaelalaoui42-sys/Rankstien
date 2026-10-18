# Stitch Atlas — Premium crochet publication preview

An independent, **ad-first** Next.js 15 craft publication prototype developed as a new Rankstien vertical. **This is a preview, not a launched or indexed website.** All pattern cards are explicitly marked as concepts until genuinely tested; there are no fictional ratings, fake subscriptions, made-up authors, or recipe schema markup.

## Pages

- `/`: editorial homepage, original photo, illustrated categories, research-stage collection, beginner feature, tools.
- `/patterns`: searchable & filterable research-stage topic library.
- `/learn`: original beginner educational reference, US/UK stitches, tension/gauge intro.
- `/tools`: persistent local-only row counter, stitch terminology reference, proportional gauge estimate.
- `/about`: explicit editorial, image rights, advertiser and privacy standards.

## Run

```bash
npm install
npm run build
npm run dev
```

No `.env` or paid accounts are needed for the prototype. `npm run test` runs a standalone structural audit, with browser viewport QA in `tests/browser.mjs` when a Playwright environment is available.

## Launch gates

1. Register/verify the chosen domain and replace `stitch-atlas.example` in metadata.
2. Approve permanent brand naming, official assets and contact details.
3. Publish **genuinely reviewed** patterns with actual photographs, stitch count checks and reviewer attestations, using craft-appropriate Article/CreativeWork metadata, not Recipe/HowTo rich-result promises.
4. Connect independent DB/CMS, pattern schema, rankstein domain partition, media uploads and an isolated Pinterest account.
5. Replace the `noindex` stage policy only once originals, canonical links, sitemap and publisher policies are ready.
6. Apply for AdSense after substantial original pages and legal pages exist; ads are not installed in this preview.
7. Validate page performance, keyboard/mobile usability at 360/390/768/1024/1440, and real LCP/INP/CLS once live.

## Assets

All custom vector logos and category illustration assets in `/public/brand` and `/public/category` are authored for Stitch Atlas. Editorial hero photo is AI-generated for the concept and is **not evidence of a physically tested pattern**. Replace or supplement with genuinely tested project photography for future pattern pages.
