# Stitch Atlas CMS and Rankstien integration — Phase 2

**Current status:** Source implementation and test suite only. The live Stitch Atlas preview is intentionally `noindex`, and the CMS is disabled until a **new, dedicated Supabase project** is provisioned. This document is not evidence a database was created or a recipe was physically tested.

## Safety / isolation boundaries

- Never execute `db/migrations/20261018_stitch_atlas_editorial.sql` against either recipe website's existing Supabase project. The app includes a hard guard rejecting those two existing project references.
- The migration creates a fresh `craft_posts`, `craft_staff`, `craft_events`, `craft_settings` schema exclusively for **crochet patterns, tutorials, stitch guides and curated roundups**. It does not create a table named `posts` or interfere with food Recipe JSON-LD.
- `craft_settings.publishing_enabled` defaults to **false**; both `CROCHET_PUBLISHING_ENABLED` and the database switch must be intentionally set later. No automated worker may bypass these gates.
- Row-level security makes public/anonymous readers see **only published** content. Contributors may author and edit their own drafts, and cannot change `status` directly to `approved`/`published`.
- Independent editor approval requires an authorized user **different from the author**. Only a publisher role can publish, and only after the quality gate is rechecked. Every transition is stored in an immutable `craft_events` audit log.
- For an original crochet *pattern*, evidence includes real yarn/hook/gauge, stitch count arithmetic, finished dimensions, rights-cleared images, a genuinely physically worked item, a named real tester, test notes and a finished-prototype photograph. Software checks declarations; the reviewer must verify physical proof before approving.
- For tutorials/guides, require original substantive educational text, appropriate US/UK terminology, licensed or original relevant imagery and complete instructions. Roundups must link to authorized sources and avoid republishing patterns.
- No simulated ratings, fabricated author identities, fictitious paid patterns, or food Recipe markup.

## Architecture

```text
Rankstien keyword research (87 sourced candidates)
  -> `crochet research` JSON (no auto publish)
  -> `python -m rankstein.crochet_handoff` JSON proposals (status=draft; empty content)
  -> Editorial desk /studio (authorized editor imports file locally)
  -> Contributor writes original content + verifies photo rights
  -> Contributor submits for independent review
  -> A separate editor assesses instruction/evidence consistency
  -> Publisher releases after BOTH launch gates are enabled
  -> Read-only public /patterns/[slug] page (CreativeWork/Article JSON-LD)
  -> Future Pinterest queue (post-publication only; exact URL/image checks)
```

The handoff workflow **never** writes directly to Supabase, Pinterest, Vercel, or public pages. Editorial approvals are human actions, not inferred from AI-generated text.

## Deployment checklist

1. Obtain the **separate Supabase project** cost quote and approval before provisioning. Do not reuse an existing recipe project's database.
2. Create one separate Supabase project and apply migration `20261018_stitch_atlas_editorial.sql` to **that project only**.
3. Configure authentication email sender and allowed redirect URLs (`https://<preview-or-real-host>/studio`). Create **real** staff users, disable public sign-ups unless needed, and bootstrap editor roles with their real Auth UUIDs; never invent staff.
4. Configure only the following on the Stitch Atlas Vercel project:

   ```dotenv
   NEXT_PUBLIC_CROCHET_SUPABASE_URL=https://<new-dedicated-project>.supabase.co
   NEXT_PUBLIC_CROCHET_SUPABASE_ANON_KEY=<that-projects-PUBLISHABLE-key>
   # Keep CROCHET_PUBLISHING_ENABLED absent / false in staging.
   CROCHET_PUBLISHING_ENABLED=false
   ```

   Never expose a Supabase `service_role` key or database password in browser code. This app uses the public key plus a signed-in person's JWT and database RLS.
5. Run isolated database RLS tests under anonymous, contributor, editor and publisher identities. Verify contributor cannot self-approve, cannot directly set `published`, and anon cannot read drafts.
6. Sign in at `/studio`; verify queues, create/edit, submit, review, change requests and immutable review history before enabling public releases.
7. Connect the approved domain, publish independent legally accurate About/Privacy/Contact pages and reviewed original content. Verify accessibility, actual photos, 360/390/768/1024/1440 UX and real Core Web Vitals.
8. Only then explicitly set the database `craft_settings.publishing_enabled = true` and server `CROCHET_PUBLISHING_ENABLED=true`; change the site's `noindex` setting in a separately reviewed deployment. Do not do these actions as part of initial preview testing.
9. Post-publication, optional Pinterest outreach can use only reviewed original photos and links to exact matching published pages. No auto-scraped competitor art.

### Bootstrapping authorized roles (after real Auth users exist)

```sql
-- Replace actual UUIDs with values from the separate project's auth.users.
-- Examples are NOT real users and this must NOT run on the recipe databases.
INSERT INTO public.craft_staff(user_id,role) VALUES
  ('<real-auth-user-uuid-1>','contributor'),
  ('<different-real-auth-user-uuid-2>','editor'),
  ('<real-publisher-auth-uuid>','publisher');
```

**Two-person minimum:** One real contributor and another real editor/publisher must independently evaluate any published work.

## API / UI

- `/studio`: passwordless email sign-in (existing staff accounts only), draft editor, licensed-image JSON input, pattern physical-testing evidence, independent review workflow and status queue.
- `GET/POST /api/studio/posts`: authenticated list and create unpublished drafts.
- `PATCH /api/studio/posts/{uuid}`: edit own draft while editable; direct status assignment is dropped and blocked by RLS.
- `POST /api/studio/posts/{uuid}` with `{action:'submit'|'approve'|'request_changes'|'publish'|'archive', notes?:string}`: server-side signed-in RPC enforcing role + quality checks. Publication is disabled by default.
- `/patterns/[slug]`: public read-only rendered article route; returns **404** when CMS unconfigured, unpublished, or archived. It uses `Article`/`CreativeWork` metadata, not cooking `Recipe` schema.
- Import JSON from `python -m rankstein.crochet_handoff` in `/studio` to prefill a *draft form*, not push a campaign into production.

## Test commands

```bash
npm install
npm run test:editorial
npm test
npm run build
npm run start
# in another terminal, if Playwright Chromium is available:
STITCH_ATLAS_BASE_URL=http://localhost:3000 npm run test:browser
```

Without dedicated database configuration, the public preview continues to function, `/studio` explains the gate, and all new `/patterns/[slug]` pages are unavailable. This fail-closed state is expected.

## Generate a research handoff without publishing

From Rankstien repository root, after its existing `crochet research` command has produced the sourced ranking report:

```bash
python -m rankstein.crochet_handoff \
  --research-json data/reports/crochet-keywords-reviewed.json \
  --output data/reports/stitch-atlas-draft-handoff.json \
  --limit 40
```

An authorized editor may import this JSON locally through `/studio`. Its proposals have `status=draft`, blank original content, no images and `test_status=untested`; they cannot be published. Search volumes stay explicitly third-party or unknown.
