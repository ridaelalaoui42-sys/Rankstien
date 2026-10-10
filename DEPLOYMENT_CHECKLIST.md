# DEPLOYMENT CHECKLIST & PRODUCTION VERIFICATION MANUAL
**Platforms:** RecetaGenial (`https://recetagenial.com`) & RecetaDolce (`https://recetadolce.com`)  
**Deployment Policy:** Verification First — Zero Destructive Actions Without Approval  
**Date:** October 10, 2026  

---

## 1. Pre-Deployment Verification Checklist

Before pushing commits to the GitHub `main` branches or promoting Vercel deployments, verify that all preflight gates pass:

- [x] **1. Independent Codebases Confirmed**:
  - `c:\Users\REDX420\Desktop\recetagenial` (`github.com/ridaelalaoui42-sys/recetagenial.git`)
  - `c:\Users\REDX420\Desktop\recetadolce` (`github.com/ridaelalaoui42-sys/recetadolce.com.git`)
  - `c:\Users\REDX420\Desktop\Rankstein` (`github.com/ridaelalaoui42-sys/Rankstien.git`)

- [x] **2. TypeScript Compilation**:
  - `recetadolce`: `npx tsc --noEmit` exits `0`.
  - `recetagenial`: `npx tsc --noEmit` exits `0`.

- [x] **3. Next.js 16.3.2 Turbopack Production Builds**:
  - `recetadolce`: `npm run build` succeeds (50/50 routes).
  - `recetagenial`: `npm run build` succeeds (52/52 routes).

- [x] **4. Database Integrity Verification**:
  - RecetaDolce: 337 live published posts; 0 placeholders; 0 cross-brand storage links; 0 savory articles.
  - RecetaGenial: 491 live published posts; 0 placeholders; 0 cross-brand storage links.

- [x] **5. Storage Bucket Isolation**:
  - RecetaDolce images hosted exclusively on `https://xjvmnmfczvwkjiasirsl.supabase.co/storage/v1/object/public/recipe-images/`.
  - RecetaGenial images hosted exclusively on `https://hokcljsrrnjxzgdhjice.supabase.co/storage/v1/object/public/`.

- [x] **6. SEO & Indexing Directives**:
  - `robots.ts` disallows `/admin/`, `/api/`, `/favorites`, `/shopping-list` on both sites.
  - `sitemap.ts` dynamic and strictly typed per brand.
  - Redirected URLs filtered out of sitemaps.

- [x] **7. Asset Preservation**:
  - 193 RecetaDolce hero images and 130 RecetaGenial hero images saved locally under `data/salvaged_images/` with metadata JSON files.

---

## 2. Safe Git Staging & Deployment Runbook

### Step 1: Commit Frontend SEO & Taxonomy Updates (RecetaDolce)
```bash
cd c:\Users\REDX420\Desktop\recetadolce
git add app/sitemap.ts app/robots.ts lib/redirects.ts lib/publication-validation.ts
git commit -m "fix(seo): restore pastry taxonomy in sitemap, disallow local storage pages in robots, add savory 301 redirects, and harden publication validation"
```

### Step 2: Commit Frontend SEO & Taxonomy Updates (RecetaGenial)
```bash
cd c:\Users\REDX420\Desktop\recetagenial
git add app/sitemap.ts app/robots.ts lib/publication-validation.ts
git commit -m "fix(seo): update dynamic typed sitemap, disallow local storage pages in robots, and harden publication validation"
```

### Step 3: Commit Automation & Validation Hardening (Rankstein)
```bash
cd c:\Users\REDX420\Desktop\Rankstein
git add backend/services/news_scraper.py rankstein_mcp_server.py
git commit -m "fix(pipeline): domain-aware validation gates, strict placeholder rejection, and cross-brand storage isolation"
```

---

## 3. Post-Deployment Verification (Smoke Tests)

Once deployed to production:
1. **Sitemap Check**:
   - `curl -I https://recetadolce.com/sitemap.xml` -> HTTP 200. Inspect content: verify 4 dessert categories present, 0 savory categories.
   - `curl -I https://recetagenial.com/sitemap.xml` -> HTTP 200. Inspect content: verify 6 culinary categories present.
2. **Robots Check**:
   - `curl https://recetadolce.com/robots.txt` -> Verify `Disallow: /favorites` and `Disallow: /shopping-list`.
   - `curl https://recetagenial.com/robots.txt` -> Verify `Disallow: /favorites` and `Disallow: /shopping-list`.
3. **Redirect Check**:
   - `curl -I https://recetadolce.com/pollo-al-horno-recetas-tradicional` -> HTTP 301 -> `https://recetadolce.com/search`.
4. **Pinterest Automation Check**:
   - Verify Pinterest supervisor continues polling queues for `r1` account boards (`Chocolate`, `Fresas` for Dolce; `Aperitivos`, `Arroces`, `Carnes`, `ENSALADES`, `Pescados` for Genial).
