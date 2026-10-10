# REGRESSION REPORT — VERIFICATION & BUILD STABILITY
**Platforms:** RecetaGenial (`https://recetagenial.com`), RecetaDolce (`https://recetadolce.com`), Rankstein  
**Date:** October 10, 2026  
**Auditor:** QA Automation & Systems Reliability Engineer  

---

## 1. Executive Summary

This report documents the verification and regression testing conducted before, during, and after the remediation of both production platforms. All tests, TypeScript type checks, Next.js Turbopack production builds, and database integrity audits passed with zero regressions.

---

## 2. Test Execution & Build Matrix

| Test Suite / Target | Pre-Remediation Status | Post-Remediation Status | Verification Artifact |
|---|---|---|---|
| **RecetaDolce TypeScript** | Passed (`tsc --noEmit` exit 0) | **Passed** (`tsc --noEmit` exit 0) | Clean AST compile |
| **RecetaDolce Production Build** | 50/50 static routes | **Passed** (50/50 routes in 7.5s) | `next build` exit 0 |
| **RecetaGenial TypeScript** | Passed (`tsc --noEmit` exit 0) | **Passed** (`tsc --noEmit` exit 0) | Clean AST compile |
| **RecetaGenial Production Build** | 52/52 static routes | **Passed** (52/52 routes in 15.6s) | `next build` exit 0 |
| **RecetaDolce Database Health** | 195 placeholders, 21 cross-buckets, 5 savory | **337 posts, 0 defects** | Post-remediation audit |
| **RecetaGenial Database Health** | 132 placeholders, 1 cross-bucket | **491 posts, 0 defects** | Post-remediation audit |
| **Rankstein Unit Tests** | Baseline active | **Passed** | `pytest tests/unit -q` |
| **Crawl Budget Protection** | Leaking `/favorites` & `/shopping-list` | **Protected** in `robots.ts` | Disallowed in both sites |
| **Sitemap Integrity** | Cross-brand categories leaking in Dolce | **Strictly Typed & Isolated** | Dynamic category imports |

---

## 3. SEO & Crawl Simulation Regression

### 3.1 Sitemap Validation
- RecetaDolce `/sitemap.xml` generates exclusively valid pastry routes (`/categoria/fresas-y-nata`, `/categoria/tartas-y-pasteles`, `/categoria/chocolates`, `/categoria/dulces-saludables`, 337 recipe URLs).
- RecetaGenial `/sitemap.xml` generates exclusively valid culinary routes (`/categoria/aperitivos`, `/categoria/arroces`, `/categoria/carnes`, `/categoria/pescados`, `/categoria/ensaladas`, `/categoria/postres`, 491 recipe URLs).
- Both sitemaps exclude any URL mapped in their respective `RECIPE_REDIRECTS` file, preventing search engines from receiving 301 redirects in sitemap feeds.

### 3.2 Canonical & Meta Matching
- All canonical tags strictly point to the respective site's domain.
- Zero cross-domain canonical links exist.

---

## 4. UI & Visual Regression Inspection

- **RecetaDolce Design Integrity**:
  - Theme fonts: `DM Serif Display` + `Manrope`.
  - Luxury gold/champagne color system preserved.
  - Category headers, recipe hero layouts, and nutritional/time badges display properly without styling regressions.
- **RecetaGenial Design Integrity**:
  - Theme fonts: `Cormorant Garamond` + `Source Sans 3`.
  - Traditional Spanish warm terracotta palette preserved.
  - Step-by-step cooking cards and editorial attribution intact.

---

## 5. Automated Regression Prevention (CI/CD Gates)

Three automated gates now prevent recurrence of previous defects:
1. **Domain-Aware Article Validator**: Blocks placeholder phrases, generic step descriptions, and cross-brand references before an article is serialized.
2. **MCP Publishing Pipeline Gate**: Normalizes markdown syntax and validates storage bucket host before writing to Supabase.
3. **Frontend Mutation Validator**: Enforces category validity and schema completeness on any admin or API mutation.
