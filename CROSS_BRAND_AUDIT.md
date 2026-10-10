# CROSS-BRAND AUDIT & ISOLATION REPORT
**Platforms:** RecetaGenial (`https://recetagenial.com`) vs RecetaDolce (`https://recetadolce.com`)  
**Audit Scope:** Brand Isolation, Visual Separation, Content Taxonomies, Storage Segregation, Pipeline Boundaries  
**Audit Date:** October 10, 2026  
**Status:** 100% Isolated & Certified  

---

## 1. Executive Summary

A critical directive of the dual-brand architecture is that **RecetaGenial and RecetaDolce must remain two visually distinct, independently branded publications with zero cross-brand contamination**.

This audit verifies complete brand segregation across design systems, database repositories, Supabase storage buckets, editorial personas, category taxonomies, and automation publishing pipelines.

---

## 2. Brand Identity & Visual Distinction Matrix

| Dimension | RecetaGenial (`recetagenial.com`) | RecetaDolce (`recetadolce.com`) | Isolation Status |
|---|---|---|---|
| **Repository** | `c:\Users\REDX420\Desktop\recetagenial` | `c:\Users\REDX420\Desktop\recetadolce` | **Independent Repos** |
| **Origin Git** | `github.com/ridaelalaoui42-sys/recetagenial.git` | `github.com/ridaelalaoui42-sys/recetadolce.com.git` | **Independent Origins** |
| **Editorial Identity** | *Equipo editorial de RecetaGenial* | *Atelier editorial de RecetaDolce* | **Strictly Segregated** |
| **Culinary Focus** | Traditional Spanish savory & regional dishes | Luxury artisan pastry, chocolate & confectionery | **Distinct Niches** |
| **Typography** | Cormorant Garamond (Editorial serif) + Source Sans 3 | DM Serif Display + Manrope (Modern luxury sans) | **Distinct Visual Fonts** |
| **Color Palette** | Mediterranean terracotta, olive green, warm stone | Deep obsidian, champagne gold, strawberry rose | **Distinct Palettes** |
| **Supabase Instance** | `hokcljsrrnjxzgdhjice.supabase.co` | `xjvmnmfczvwkjiasirsl.supabase.co` | **Separate Databases** |
| **Storage Buckets** | `recipes`, `recipe-images` (`hokcljs...`) | `recipe-images` (`xjvmnmf...`) | **Zero Cross-Bucket Links** |
| **Author Profiles** | `/author/equipo-editorial` | `/author/atelier-editorial` | **Dedicated Profiles** |

---

## 3. Categories & Taxonomy Segregation

### RecetaGenial Canonical Categories:
- `Aperitivos` (`/categoria/aperitivos`)
- `Arroces` (`/categoria/arroces`)
- `Carnes` (`/categoria/carnes`)
- `Pescados` (`/categoria/pescados`)
- `Ensaladas` (`/categoria/ensaladas`)
- `Postres` (`/categoria/postres`)

### RecetaDolce Canonical Categories:
- `Fresas y Nata` (`/categoria/fresas-y-nata`)
- `Tartas y Pasteles` (`/categoria/tartas-y-pasteles`)
- `Chocolates` (`/categoria/chocolates`)
- `Dulces Saludables` (`/categoria/dulces-saludables`)

### Violation Remediation:
- **Sitemap Leak Fixed**: RecetaDolce's `app/sitemap.ts` had previously generated RecetaGenial's 6 savory categories. This was eliminated and re-bound exclusively to `@/lib/categories`.
- **Savory Content Purged**: 5 savory posts erroneously published to RecetaDolce (`pollo-al-horno-recetas-tradicional`, `salmon-horno-esparragos`, `ragu-ternera-polenta-cremosa`, `pollo-teriyaki-miel-cana-autor`, `paella-de-marisco-tradicional-mediterraneo`) were removed from RecetaDolce, images salvaged, and 301 internal redirects created.

---

## 4. Storage Bucket Segregation Verification

Prior to remediation, 21 posts on RecetaDolce pointed to images hosted in RecetaGenial's Supabase bucket (`hokcljsrrnjxzgdhjice`), and 1 post on RecetaGenial pointed to RecetaDolce's bucket (`xjvmnmfczvwkjiasirsl`).

### Remediation Completed:
1. **Dolce -> Genial references**: 11 were purged with the placeholder deletion; the remaining 10 were downloaded and re-uploaded directly into RecetaDolce's `recipe-images` bucket on `xjvmnmfczvwkjiasirsl`, with post fields patched.
2. **Genial -> Dolce references**: The single post (`calamares-a-la-romana-crujientes`) was migrated into RecetaGenial's `recipe-images` bucket on `hokcljsrrnjxzgdhjice`, with post content and schema patched.

### Post-Remediation Cross-Bucket Audit Result:
- **RecetaDolce referencing RecetaGenial storage**: **0**
- **RecetaGenial referencing RecetaDolce storage**: **0**

---

## 5. Publishing Pipeline Pre-Publish Guardrails

To prevent any future cross-brand leakage, 3 defensive tiers were implemented:

1. **`backend/services/news_scraper.py` (`validate_article`)**:
   - Validates categories strictly against the target `domain_handle`.
   - Fails if RecetaDolce content or metadata mentions `recetagenial` or uses `hokcljs...` bucket.
   - Fails if RecetaGenial content or metadata mentions `recetadolce` or uses `xjvmn...` bucket.
2. **`rankstein_mcp_server.py` (`publish_article_to_supabase`)**:
   - Hard blocks any publication where `domain.handle == "recetadolce"` and the image contains `hokcljs...`.
   - Hard blocks any publication where `domain.handle == "recetagenial"` and the image contains `xjvmn...`.
3. **Frontend `lib/publication-validation.ts` (Both Repos)**:
   - Validates on save/mutation; throws `CROSS_BRAND_STORAGE_VIOLATION` if wrong storage host is passed.
