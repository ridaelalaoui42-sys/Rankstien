# Stitch Atlas Maker Academy — Free illustrated crochet learning journeys

**Stage:** Brand preview, noindex, no independent CMS project or production domain.
**Purpose:** High-value, genuinely original, ad-friendly editorial education, not paid patterns or fictitious physically tested craft designs.

## What is delivered

- `/academy`: premium illustrated learning dashboard, three journeys, real local progress meter, six attainable collectible badges, reset option.
- `/academy/[pathId]`: accessible four-stage path with strong internal links and visible saved completion.
- `/academy/[pathId]/[lessonId]`: illustrated micro-lesson and three-question checkpoint with explanations, retry, 2-of-3 passing score and perfect-bonus points. No countdown or monetary rewards.
- `/guides`: twelve substantive original technique references, now six more than the previous release. Each new guide includes five developed sections, practical checks, original illustrated schematics, related internal links and cited standards.
- Twelve branded 1000×1500 Pinterest visuals (`/pins/*.png`), all drafts. No Pinterest API calls or external publishing destinations until a verified domain is configured.
- New graphics: `/public/guides/*.svg`, `/public/academy/*.svg` (three journey cover SVGs and six original badge illustrations).

## Content and learning path map

| Journey | Four lessons |
| --- | --- |
| **The First Stitches** | US/UK conversion; yarn weight and hook sizing; stitch counting; adjustable magic ring |
| **Read the Fabric** | Moss stitch; right/wrong side; measuring gauge; shaping and stitch math |
| **The Bag Maker Studio** | Choosing bag yarn; reducing strap stretch; lining a bag; weaving in yarn ends |

Each lesson links to a related free article. These are technique lessons; no untested pattern is presented as a verified original finished object.

## Gamification state contract

- A checkpoint comprises three original multiple-choice questions with explanations. Two correct answers complete a lesson; three earn a perfect score.
- Points: 50 per completed lesson, plus 25 bonus for a perfect best score. Replaying a completed quiz cannot farm points or reduce the recorded best score.
- Badges are computed, not arbitrarily granted: First Loop (any completion), Perfect Swatch (any perfect quiz), Foundation Finder (journey 1 complete), Stitch Detective (journey 2 complete), Thoughtful Maker (journey 3 complete), Atlas Explorer (all twelve completed).
- There are **no artificial content locks**. Learning sequences are suggestions, but free guides and lessons remain accessible to anyone.
- Data is stored under `stitch-atlas.academy.progress.v1` in *this browser's* `localStorage`. No authentication, cookies, remote collection, cross-device sync, or claims of formal certification. Reset clears only this academy key, not the editorial studio's saved drafts.
- Browser or private-mode restrictions can prevent persistence. The interface discloses that and still allows reading/quizzes. No false promise of backups.
- Content validators ensure unknown IDs and invalid scores cannot be treated as progress. Browser local storage is not a security boundary: badges are fun milestones, not verifiable proof of human mastery.

## SEO and AdSense readiness

1. Domain verification, canonical links, legal/contact pages, content and original image-rights verification come before lifting the site-wide `noindex` and `Disallow: /` preview gates.
2. Source-based, practical educational content should provide value beyond a generated quiz. Avoid duplicating page intent between `guides/slug` and `academy/path/slug`; long-form canonical resources are the guides, interactive micro-lessons are useful supplementary experiences.
3. Future ads should be reserved outside exercise answer targets, accessible choices and the progress interface. Avoid interstitials that interrupt questions or cause layout shifts.
4. Pinterest pin queue remains `approvedToPublish=false`, `destinationHost=null`, `autopublish=false` until a real canonical URL and legitimate media rights are confirmed.
5. Educational photos/diagrams are labelled as schematics and must never be framed as proof of an independently crocheted or safety-tested pattern.

## Verification steps

```bash
cd apps/stitch-atlas
npm install
npm run test:academy
npm run test:guides
npm run test:editorial
npm run build
# In a Playwright-enabled environment: start the built site, then run npm run test:browser
```

GitHub PR CI runs the same checks and responsive browser QA at 360, 390, 768, 1024 and 1440 pixels. No Supabase migration is required and nothing in this release touches existing recipe blog databases.

## Source notes

The yarn-weight and hook-size explanations follow the Craft Yarn Council's published recommended ranges and their explicit warning that these are *starting guidelines*, not an actual pattern gauge guarantee:
- https://media.craftyarncouncil.com/standards/yarn-weight-system
- https://www.craftyarncouncil.com/standards/hooks-and-needles
- https://www.craftyarncouncil.com/standards/crochet-abbreviations

Original Stitch Atlas editorial interpretation, not a reproduction of proprietary charts or pattern instructions.
