# Production Completion Checklist

Updated: 2026-10-08

Work is not complete until live delivery and recovery are proven. Code tests,
queued pins, and profile directories are not delivery proof.

## In Progress

- [ ] Resource protection, safe cache maintenance, nested log retention.
- [ ] Codex availability, bounded fallback and quota recovery.
- [ ] Spanish human-recipe keyword intent and correct domain categories.
- [ ] Mixed scraped/generated source provenance with 15 pairs and 30 assets.
- [ ] Complete campaign recovery and verified Pinterest delivery.
- [ ] Truthful SEO metrics and unknown/zero/error states.
- [ ] Compact operator status, validated controls, sanitized diagnostics.
- [ ] Single service ownership, daily schedule, watchdog and recovery tests.
- [ ] Queue admission, backlog health, fair routing and backpressure.
- [ ] Backups, isolated restore test, release evidence and rollback runbook.
- [ ] Blog content/schema consistency, UI and deployed production QA.
- [ ] Canonical documentation and current validation baseline.

## Human Inputs And Scope

- Run the two configured accounts while the user supplies eight additional
  account handles and authenticated profiles. Do not fabricate accounts.
- Generated source replacements are authorized when scraping is insufficient.
  Each replacement must record its actual provider, prompt, source kind and
  image hash; it must never claim a scraped Pinterest identity.
- Preserve active profiles, queued media, credential files and campaign proof.
- Containerization is optional after the host runtime passes reliability gates.

## Release Gates

- Verified article, storage and primary-pin proof for each configured domain.
- Thirty validated current-run assets and unique jobs, then actual upload proof.
- Focused/full tests, isolated automation validation, cold-start/recovery and
  backup restore checks. Record unverified gates explicitly.
- A 24-72 hour soak within domain/account budgets before account expansion.
