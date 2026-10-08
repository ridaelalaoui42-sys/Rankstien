# File-by-file Project Audit

Generated: 2026-10-08T18:32:59.837777+00:00
Root: `C:\Users\REDX420\Desktop\Rankstein`

## Summary

- Files audited: 414
- OK: 379
- Review: 35
- Fail: 0

## Scope

Included: project-owned source, tests, scripts, config, canonical docs, memory prompts, and domain manifests/roadmaps.
Excluded: dependencies, caches, browser sessions, generated media, local reports, and runtime output folders.

## Files

| Status | Kind | Lines | Bytes | File | Findings |
|---|---|---:|---:|---|---|
| ok | agent-config | 65 | 1824 | `.gemini/settings.json` |  |
| ok | docs | 131 | 10997 | `README.md` |  |
| ok | backend | 2 | 48 | `backend/__init__.py` |  |
| ok | backend | 2 | 25 | `backend/agents/__init__.py` |  |
| ok | backend | 72 | 3633 | `backend/agents/author.py` |  |
| ok | backend | 81 | 3014 | `backend/agents/base.py` |  |
| ok | backend | 35 | 1530 | `backend/agents/ceo.py` |  |
| ok | backend | 36 | 1445 | `backend/agents/layout_agent.py` |  |
| ok | backend | 47 | 1885 | `backend/agents/lupa.py` |  |
| ok | backend | 33 | 1569 | `backend/agents/manager.py` |  |
| ok | backend | 219 | 9967 | `backend/agents/orchestrator.py` |  |
| ok | backend | 38 | 2091 | `backend/agents/pinterest.py` |  |
| ok | backend | 389 | 15199 | `backend/agents/pinterest_uploader_v4.py` |  |
| ok | backend | 20 | 2042 | `backend/agents/production_contract.py` |  |
| ok | backend | 36 | 1264 | `backend/agents/publisher.py` |  |
| ok | backend | 36 | 1663 | `backend/agents/researcher.py` |  |
| ok | backend | 37 | 1673 | `backend/agents/strategist.py` |  |
| ok | backend | 37 | 2150 | `backend/agents/studio.py` |  |
| ok | backend | 40 | 1609 | `backend/agents/validator.py` |  |
| ok | backend | 2 | 29 | `backend/api/__init__.py` |  |
| ok | backend | 34 | 1463 | `backend/api/operator_auth.py` |  |
| ok | backend | 2234 | 82331 | `backend/api/operator_routes.py` |  |
| ok | backend | 435 | 17098 | `backend/api/routes.py` |  |
| ok | backend | 2 | 31 | `backend/core/__init__.py` |  |
| ok | backend | 124 | 4836 | `backend/core/a2a_protocol.py` |  |
| ok | backend | 81 | 3099 | `backend/core/config.py` |  |
| ok | backend | 633 | 22958 | `backend/core/database.py` |  |
| ok | backend | 239 | 8254 | `backend/core/engine.py` |  |
| ok | backend | 63 | 2087 | `backend/core/security.py` |  |
| ok | backend | 86 | 2824 | `backend/main.py` |  |
| ok | backend | 67 | 2044 | `backend/operator.py` |  |
| ok | backend | 23 | 432 | `backend/requirements.txt` |  |
| ok | backend | 179 | 6471 | `backend/scripts/batch_upload_all_remastered.py` |  |
| ok | backend | 695 | 24074 | `backend/scripts/batch_upload_remastered.py` |  |
| ok | backend | 7 | 112 | `backend/scripts/batch_upload_turbo.py` |  |
| ok | backend | 27 | 932 | `backend/scripts/check_unpinned.py` |  |
| ok | backend | 298 | 11065 | `backend/scripts/clear_pinterest_drafts.py` |  |
| ok | backend | 82 | 2632 | `backend/scripts/daily_engine.py` |  |
| ok | backend | 109 | 3561 | `backend/scripts/deploy_asset.py` |  |
| ok | backend | 116 | 4381 | `backend/scripts/deploy_generic.py` |  |
| ok | backend | 110 | 4271 | `backend/scripts/deploy_v2.py` |  |
| ok | backend | 33 | 1199 | `backend/scripts/dual_turbo.py` |  |
| ok | backend | 48 | 1405 | `backend/scripts/fix_post.py` |  |
| ok | backend | 50 | 1799 | `backend/scripts/force_fix_visibility.py` |  |
| ok | backend | 106 | 2872 | `backend/scripts/gemini_token_rotator.py` |  |
| ok | backend | 642 | 20136 | `backend/scripts/hero_image_pipeline.py` |  |
| ok | backend | 1615 | 63458 | `backend/scripts/pinterest_batch_core.py` |  |
| ok | backend | 656 | 25121 | `backend/scripts/pinterest_uploader_v4.py` |  |
| ok | backend | 33 | 806 | `backend/scripts/trigger_funnel.py` |  |
| ok | backend | 4053 | 163512 | `backend/scripts/turbo_articles.py` |  |
| ok | backend | 2 | 27 | `backend/services/__init__.py` |  |
| ok | backend | 75 | 2665 | `backend/services/competitor_analyzer.py` |  |
| ok | backend | 140 | 5324 | `backend/services/harvester.py` |  |
| ok | backend | 109 | 3900 | `backend/services/keyword_mapper.py` |  |
| ok | backend | 177 | 6911 | `backend/services/memory_service.py` |  |
| ok | backend | 642 | 24384 | `backend/services/news_scraper.py` |  |
| ok | backend | 89 | 3017 | `backend/services/nvidia_client.py` |  |
| ok | backend | 1395 | 53717 | `backend/services/operator_pipeline.py` |  |
| ok | backend | 2477 | 102582 | `backend/services/remasterer.py` |  |
| ok | backend | 167 | 6802 | `backend/services/scraper.py` |  |
| ok | backend | 147 | 4748 | `backend/services/seo_tools.py` |  |
| ok | backend | 108 | 4271 | `backend/services/site_auditor.py` |  |
| ok | backend | 16 | 880 | `backend/static/operator/LUCIDE_LICENSE.txt` |  |
| ok | backend | 564 | 23486 | `backend/static/operator/index.html` |  |
| ok | backend | 13 | 357796 | `backend/static/operator/lucide.min.js` |  |
| ok | backend | 1291 | 22614 | `backend/static/operator/operator.css` |  |
| ok | backend | 1674 | 66614 | `backend/static/operator/operator.js` |  |
| ok | docs | 63 | 1825 | `cli-harness/README.md` |  |
| ok | docs | 52 | 1558 | `cli-harness/SKILL.md` |  |
| ok | docs | 69 | 2360 | `cli-harness/cli_anything_rankstein/HARNESS.md` |  |
| ok | project | 4 | 104 | `cli-harness/cli_anything_rankstein/__init__.py` |  |
| ok | project | 471 | 19685 | `cli-harness/cli_anything_rankstein/__main__.py` |  |
| ok | project | 23 | 546 | `cli-harness/pyproject.toml` |  |
| ok | domain-data | 311 | 13615 | `data/domains/recetadolce/daily_best_keywords.json` |  |
| ok | docs | 21 | 1404 | `data/domains/recetadolce/daily_best_keywords.md` |  |
| ok | domain-data | 36 | 1138 | `data/domains/recetadolce/domain.json` |  |
| ok | docs | 744 | 85573 | `data/domains/recetadolce/keywords.md` |  |
| ok | domain-data | 358 | 17360 | `data/domains/recetagenial/daily_best_keywords.json` |  |
| ok | docs | 22 | 1361 | `data/domains/recetagenial/daily_best_keywords.md` |  |
| ok | domain-data | 40 | 1174 | `data/domains/recetagenial/domain.json` |  |
| ok | docs | 511 | 57914 | `data/domains/recetagenial/keywords.md` |  |
| ok | docs | 96 | 4883 | `docs/system/AUTONOMOUS_AGENTIC_SYSTEM.md` |  |
| ok | docs | 111 | 11732 | `docs/system/CAMPAIGN_PIPELINE.md` |  |
| ok | docs | 0 | 0 | `docs/system/HERMES_SOUL.md` |  |
| ok | docs | 70 | 3542 | `docs/system/OPERATOR_DASHBOARD.md` |  |
| ok | docs | 40 | 1999 | `docs/system/PRODUCTION_COMPLETION.md` |  |
| ok | docs | 200 | 9578 | `docs/system/PRODUCTION_RUNTIME_PLAN.md` |  |
| ok | docs | 70 | 2201 | `docs/system/PROJECT_HYGIENE.md` |  |
| ok | docs | 75 | 4329 | `docs/system/PROJECT_MAP.md` |  |
| ok | docs | 325 | 16084 | `docs/system/SYSTEM_ARCHITECTURE.md` |  |
| ok | docs | 398 | 12595 | `docs/templates/GENERIC_PINTEREST_PIN_TEMPLATE.md` |  |
| ok | docs | 94 | 6821 | `docs/templates/IMAGE_GENERATION_CONTRACT.md` |  |
| ok | docs | 104 | 3427 | `docs/templates/TRIGGER_RECIPE_BRAIN.md` |  |
| ok | docs | 0 | 0 | `docs/templates/UPCOMING_DOMAIN_SYSTEM_PROMPT.md` |  |
| ok | frontend | 12 | 520 | `frontend/.vercel/README.txt` |  |
| ok | frontend | 1 | 122 | `frontend/.vercel/project.json` |  |
| ok | docs | 18 | 1805 | `frontend/AGENTS.md` |  |
| ok | docs | 6 | 292 | `frontend/CLAUDE.md` |  |
| ok | docs | 44 | 2103 | `frontend/CONTENT_WIZARD.md` |  |
| ok | docs | 34 | 1921 | `frontend/PLUGINS.md` |  |
| ok | docs | 42 | 1055 | `frontend/README.md` |  |
| ok | frontend | 48 | 1713 | `frontend/app/[slug]/error.tsx` |  |
| ok | frontend | 42 | 1857 | `frontend/app/[slug]/loading.tsx` |  |
| ok | frontend | 529 | 20776 | `frontend/app/[slug]/page.tsx` |  |
| ok | frontend | 190 | 12281 | `frontend/app/about/page.tsx` |  |
| ok | frontend | 50 | 1457 | `frontend/app/admin/edit/[id]/page.tsx` |  |
| ok | frontend | 90 | 3209 | `frontend/app/admin/login/page.tsx` |  |
| ok | frontend | 31 | 957 | `frontend/app/admin/new/page.tsx` |  |
| ok | frontend | 214 | 9179 | `frontend/app/admin/newsletter/page.tsx` |  |
| ok | frontend | 208 | 9740 | `frontend/app/admin/page.tsx` |  |
| ok | frontend | 244 | 10232 | `frontend/app/admin/seo-audit/page.tsx` |  |
| ok | frontend | 725 | 37502 | `frontend/app/admin/settings/page.tsx` |  |
| ok | frontend | 63 | 1837 | `frontend/app/api/admin/auth/route.ts` |  |
| ok | frontend | 42 | 1444 | `frontend/app/api/admin/newsletter/send/route.ts` |  |
| ok | frontend | 21 | 949 | `frontend/app/api/admin/posts/[id]/route.ts` |  |
| ok | frontend | 12 | 488 | `frontend/app/api/admin/posts/route.ts` |  |
| ok | frontend | 91 | 2482 | `frontend/app/api/admin/seo/audit/route.ts` |  |
| ok | frontend | 70 | 2069 | `frontend/app/api/admin/settings/route.ts` |  |
| ok | frontend | 36 | 1055 | `frontend/app/api/newsletter/subscribe/route.ts` |  |
| ok | frontend | 39 | 1148 | `frontend/app/api/posts/related/[slug]/route.ts` |  |
| ok | frontend | 164 | 5343 | `frontend/app/api/publish/route.ts` |  |
| ok | frontend | 316 | 12581 | `frontend/app/categoria/[slug]/page.tsx` |  |
| ok | frontend | 223 | 9135 | `frontend/app/category/[slug]/page.tsx` |  |
| ok | frontend | 105 | 5854 | `frontend/app/contact/page.tsx` |  |
| ok | frontend | 76 | 4461 | `frontend/app/cookies/page.tsx` |  |
| ok | frontend | 607 | 15285 | `frontend/app/globals.css` |  |
| ok | frontend | 108 | 6202 | `frontend/app/guia-higiene/page.tsx` |  |
| ok | frontend | 231 | 8734 | `frontend/app/layout.tsx` |  |
| ok | frontend | 65 | 3397 | `frontend/app/not-found.tsx` |  |
| ok | frontend | 179 | 9877 | `frontend/app/nuestra-historia/page.tsx` |  |
| ok | frontend | 266 | 13825 | `frontend/app/page.tsx` |  |
| ok | frontend | 91 | 4957 | `frontend/app/privacy/page.tsx` |  |
| ok | frontend | 219 | 11688 | `frontend/app/recetas/pollo-al-ajillo-facil/page.tsx` |  |
| ok | frontend | 180 | 3211 | `frontend/app/recetas/pollo-al-ajillo-facil/recipe.module.css` |  |
| ok | frontend | 17 | 336 | `frontend/app/robots.ts` |  |
| ok | frontend | 102 | 4588 | `frontend/app/search/page.tsx` |  |
| ok | frontend | 106 | 6381 | `frontend/app/seguridad-alimentaria/page.tsx` |  |
| ok | frontend | 48 | 2018 | `frontend/app/sitemap.ts` |  |
| ok | frontend | 66 | 3649 | `frontend/app/terms/page.tsx` |  |
| ok | frontend | 69 | 2296 | `frontend/components/AdUnit.tsx` |  |
| ok | frontend | 21 | 446 | `frontend/components/AdminCheck.tsx` |  |
| ok | frontend | 84 | 5777 | `frontend/components/AuthorBio.tsx` |  |
| ok | frontend | 47 | 1481 | `frontend/components/Breadcrumbs.tsx` |  |
| ok | frontend | 333 | 19256 | `frontend/components/CollapsibleCard.tsx` |  |
| ok | frontend | 154 | 5841 | `frontend/components/Comments.tsx` |  |
| ok | frontend | 69 | 3183 | `frontend/components/ContactForm.tsx` |  |
| ok | frontend | 65 | 2741 | `frontend/components/CookieBanner.tsx` |  |
| ok | frontend | 43 | 1991 | `frontend/components/CuisineGrid.tsx` |  |
| ok | frontend | 27 | 766 | `frontend/components/DeleteButton.tsx` |  |
| ok | frontend | 29 | 847 | `frontend/components/DeterministicDate.tsx` |  |
| ok | frontend | 117 | 6165 | `frontend/components/EEATSignals.tsx` |  |
| ok | frontend | 73 | 3016 | `frontend/components/ExitIntentPopup.tsx` |  |
| ok | frontend | 122 | 5318 | `frontend/components/FloatingNewsletter.tsx` |  |
| ok | frontend | 84 | 4118 | `frontend/components/Footer.tsx` |  |
| ok | frontend | 328 | 15035 | `frontend/components/Header.tsx` |  |
| ok | frontend | 93 | 4444 | `frontend/components/HorizontalFeaturedCard.tsx` |  |
| ok | frontend | 35 | 892 | `frontend/components/LogoutButton.tsx` |  |
| ok | frontend | 95 | 3899 | `frontend/components/NewsletterForm.tsx` |  |
| ok | frontend | 67 | 4169 | `frontend/components/NewsletterSection.tsx` |  |
| ok | frontend | 61 | 2947 | `frontend/components/PinterestPin.tsx` |  |
| ok | frontend | 293 | 13199 | `frontend/components/PostForm.tsx` |  |
| ok | frontend | 17 | 486 | `frontend/components/PrintButton.tsx` |  |
| ok | frontend | 127 | 5564 | `frontend/components/QuickViewModal.tsx` |  |
| ok | frontend | 52 | 1466 | `frontend/components/ReadingProgress.tsx` |  |
| ok | frontend | 326 | 17127 | `frontend/components/RecipeDetails.tsx` |  |
| ok | frontend | 36 | 1035 | `frontend/components/RecipeGrid.tsx` |  |
| ok | frontend | 30 | 859 | `frontend/components/RecipeGridToggle.tsx` |  |
| ok | frontend | 58 | 2151 | `frontend/components/RelatedPosts.tsx` |  |
| ok | frontend | 228 | 9919 | `frontend/components/ReviewSystem.tsx` |  |
| ok | frontend | 45 | 1437 | `frontend/components/SafeImage.tsx` |  |
| ok | frontend | 32 | 863 | `frontend/components/SchemaMarkup.tsx` |  |
| ok | frontend | 92 | 3619 | `frontend/components/SearchBar.tsx` |  |
| ok | frontend | 103 | 3764 | `frontend/components/ShareMenu.tsx` |  |
| ok | frontend | 145 | 6648 | `frontend/components/Sidebar.tsx` |  |
| ok | frontend | 30 | 1151 | `frontend/components/SocialStats.tsx` |  |
| ok | frontend | 68 | 3025 | `frontend/components/StandardRecipeCard.tsx` |  |
| ok | frontend | 102 | 3548 | `frontend/components/StarRating.tsx` |  |
| ok | frontend | 93 | 3511 | `frontend/components/newsletter/NewsletterBox.tsx` |  |
| ok | frontend | 28 | 898 | `frontend/components/recipe/FAQSection.tsx` |  |
| ok | frontend | 50 | 1575 | `frontend/components/recipe/IngredientsList.tsx` |  |
| ok | frontend | 20 | 533 | `frontend/components/recipe/PrintLink.tsx` |  |
| ok | frontend | 86 | 3339 | `frontend/components/recipe/RecipeHero.tsx` |  |
| ok | frontend | 114 | 4393 | `frontend/components/recipe/RelatedRecipes.tsx` |  |
| ok | frontend | 66 | 2589 | `frontend/components/recipe/SocialShare.tsx` |  |
| ok | frontend | 66 | 2375 | `frontend/components/recipe/StepByStep.tsx` |  |
| ok | frontend | 25 | 521 | `frontend/context/SettingsContext.tsx` |  |
| ok | frontend | 31 | 731 | `frontend/eslint.config.mjs` |  |
| ok | frontend | 16 | 692 | `frontend/fetch_slug.js` |  |
| ok | frontend | 16 | 671 | `frontend/fetch_slug_genial.js` |  |
| ok | frontend | 33 | 1226 | `frontend/fix_db_content.js` |  |
| ok | frontend | 36 | 1407 | `frontend/fix_db_content2.js` |  |
| ok | frontend | 36 | 1341 | `frontend/fix_recetagenial_db.js` |  |
| ok | frontend | 63 | 2421 | `frontend/lib/categories.ts` |  |
| ok | frontend | 74 | 2174 | `frontend/lib/imageHelper.ts` |  |
| ok | frontend | 67 | 2515 | `frontend/lib/sanitize.ts` |  |
| ok | frontend | 23 | 524 | `frontend/lib/settings.ts` |  |
| ok | frontend | 14 | 1165 | `frontend/lib/siteImages.ts` |  |
| ok | frontend | 77 | 2813 | `frontend/lib/supabase.ts` |  |
| ok | frontend | 38 | 896 | `frontend/lib/utils.ts` |  |
| ok | frontend | 50 | 2200 | `frontend/migrate_post.js` |  |
| ok | frontend | 38 | 1423 | `frontend/models.json` |  |
| ok | frontend | 7 | 253 | `frontend/next-env.d.ts` |  |
| ok | frontend | 106 | 3067 | `frontend/next.config.ts` |  |
| ok | frontend | 12 | 303 | `frontend/nexus_config.json` |  |
| ok | frontend | 7133 | 254173 | `frontend/package-lock.json` |  |
| ok | frontend | 47 | 1100 | `frontend/package.json` |  |
| ok | frontend | 62 | 7727 | `frontend/post_content.txt` |  |
| ok | frontend | 62 | 7727 | `frontend/post_content_recetagenial.txt` |  |
| ok | frontend | 8 | 101 | `frontend/postcss.config.mjs` |  |
| ok | frontend | 23 | 633 | `frontend/proxy.ts` |  |
| ok | frontend | 27 | 1002 | `frontend/public/llms.txt` |  |
| ok | frontend | 177 | 6186 | `frontend/schema.sql` |  |
| ok | frontend | 40 | 1157 | `frontend/scripts/batch_publish.js` |  |
| ok | frontend | 196 | 9555 | `frontend/scripts/campaign_manager.py` |  |
| ok | frontend | 138 | 3712 | `frontend/scripts/campaigns/fresas_campaign.json` |  |
| ok | frontend | 341 | 13629 | `frontend/scripts/content_wizard.py` |  |
| ok | frontend | 50 | 1749 | `frontend/scripts/debug_db.js` |  |
| ok | frontend | 212 | 9999 | `frontend/scripts/generate_pins.py` |  |
| ok | frontend | 135 | 19204 | `frontend/scripts/publish_fresas.py` |  |
| ok | frontend | 131 | 22532 | `frontend/scripts/publish_tapas.py` |  |
| ok | frontend | 60 | 2574 | `frontend/scripts/seed_admin.js` |  |
| ok | frontend | 51 | 1738 | `frontend/scripts/sync_nexus.py` |  |
| ok | frontend | 46 | 1401 | `frontend/scripts/update_analytics.js` |  |
| ok | frontend | 49 | 1589 | `frontend/scripts/update_head_code.js` |  |
| ok | frontend | 22 | 622 | `frontend/test_marked.js` |  |
| ok | frontend | 23 | 872 | `frontend/test_marked2.js` |  |
| ok | frontend | 45 | 818 | `frontend/tsconfig.json` |  |
| ok | frontend | 129 | 2847 | `frontend/types/index.ts` |  |
| ok | frontend | 17 | 419 | `frontend/vercel.json` |  |
| ok | docs | 32 | 1898 | `memory/gold_config.md` |  |
| ok | project | 180 | 5302 | `memory/keyword_clusters.json` |  |
| ok | docs | 214 | 23347 | `memory/keywords.md` |  |
| ok | docs | 22 | 1615 | `memory/pinterest_backlog.md` |  |
| ok | core | 55 | 1956 | `pinterest_automation/__init__.py` |  |
| ok | core | 233 | 8588 | `pinterest_automation/browser_utils.py` |  |
| ok | core | 861 | 31325 | `pinterest_automation/campaign.py` |  |
| ok | core | 246 | 9752 | `pinterest_automation/circuit_breaker.py` |  |
| ok | core | 457 | 16502 | `pinterest_automation/config.py` |  |
| ok | core | 281 | 11121 | `pinterest_automation/health_monitor.py` |  |
| ok | core | 1331 | 55174 | `pinterest_automation/job_queue.py` |  |
| ok | core | 282 | 11776 | `pinterest_automation/mcp_bridge.py` |  |
| ok | core | 172 | 6217 | `pinterest_automation/mcp_client.py` |  |
| ok | core | 343 | 12660 | `pinterest_automation/mcp_integration.py` |  |
| ok | core | 1317 | 58562 | `pinterest_automation/pinterest_driver.py` |  |
| ok | core | 317 | 13518 | `pinterest_automation/rate_limiter.py` |  |
| ok | core | 53 | 1742 | `pinterest_automation/routing.py` |  |
| ok | core | 152 | 5309 | `pinterest_automation/runtime_state.py` |  |
| ok | core | 568 | 22061 | `pinterest_automation/self_healing.py` |  |
| ok | core | 485 | 20430 | `pinterest_automation/session_pool.py` |  |
| ok | core | 818 | 38348 | `pinterest_automation/supervisor.py` |  |
| ok | core | 61 | 1897 | `pinterest_automation/utils.py` |  |
| ok | project | 249 | 8197 | `pyproject.toml` |  |
| ok | project | 39 | 1405 | `rankstein.py` |  |
| ok | core | 19 | 724 | `rankstein/__init__.py` |  |
| ok | core | 109 | 3506 | `rankstein/autonomous.py` |  |
| ok | core | 266 | 10888 | `rankstein/branding.py` |  |
| ok | core | 200 | 8188 | `rankstein/category_policy.py` |  |
| ok | core | 815 | 34316 | `rankstein/cli.py` |  |
| ok | core | 214 | 9920 | `rankstein/config.py` |  |
| ok | core | 313 | 13160 | `rankstein/domain.py` |  |
| ok | core | 283 | 11629 | `rankstein/ga4_connector.py` |  |
| ok | core | 143 | 5712 | `rankstein/google_trends_connector.py` |  |
| ok | core | 244 | 9650 | `rankstein/gsc_connector.py` |  |
| ok | core | 294 | 9883 | `rankstein/keyword_roadmap.py` |  |
| ok | core | 694 | 24260 | `rankstein/launcher.py` |  |
| ok | core | 138 | 5529 | `rankstein/log_manager.py` |  |
| ok | core | 455 | 20762 | `rankstein/niche_detector.py` |  |
| ok | core | 130 | 4946 | `rankstein/pinterest_connector.py` |  |
| ok | core | 230 | 6522 | `rankstein/pipeline_events.py` |  |
| ok | core | 882 | 40072 | `rankstein/production_batch.py` |  |
| ok | core | 569 | 21078 | `rankstein/production_reconcile.py` |  |
| ok | core | 490 | 15326 | `rankstein/prompts.py` |  |
| ok | core | 383 | 16413 | `rankstein/provisioner.py` |  |
| ok | core | 817 | 27641 | `rankstein/recipe_pin_generator.py` |  |
| ok | core | 830 | 29178 | `rankstein/remaster_variants.py` |  |
| ok | core | 36 | 1295 | `rankstein/runtime_env.py` |  |
| ok | core | 829 | 37614 | `rankstein/seo_feedback_engine.py` |  |
| ok | core | 697 | 24047 | `rankstein/site_factory.py` |  |
| ok | core | 166 | 6386 | `rankstein/source_image_quality.py` |  |
| ok | core | 401 | 15062 | `rankstein/startup.py` |  |
| ok | core | 181 | 6033 | `rankstein/subscribers.py` |  |
| ok | core | 611 | 22636 | `rankstein/suite_controller.py` |  |
| ok | core | 1836 | 62916 | `rankstein/trend_intelligence.py` |  |
| ok | core | 29 | 886 | `rankstein/windows_compat.py` |  |
| ok | project | 5424 | 228479 | `rankstein_mcp_server.py` |  |
| ok | project | 193 | 4121 | `requirements.txt` |  |
| review | scripts | 355 | 21070 | `scripts/debug/audit_blog_admin.cjs` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 121 | 7413 | `scripts/debug/audit_blog_preview.cjs` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 70 | 2835 | `scripts/debug/capture_operator_dashboard.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 45 | 1608 | `scripts/debug/check_articles.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 38 | 1533 | `scripts/debug/check_fresh_keywords.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 45 | 1677 | `scripts/debug/check_models.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 11 | 407 | `scripts/debug/check_nvidia_log.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 19 | 875 | `scripts/debug/check_proof.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 45 | 1682 | `scripts/debug/check_published_today.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 32 | 1173 | `scripts/debug/dump_posts.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 39 | 1651 | `scripts/debug/fetch_urls.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 6 | 522 | `scripts/debug/find_recent.ps1` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 15 | 469 | `scripts/debug/find_tables.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 195 | 13475 | `scripts/debug/generate_ensalada_pasta.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 197 | 14668 | `scripts/debug/generate_tarta_tatin.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 70 | 2431 | `scripts/debug/inspect_pinterest_remaster_dom.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 26 | 1554 | `scripts/debug/operator_accessibility_audit.js` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 183 | 7483 | `scripts/debug/operator_browser_audit.js` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 49 | 2546 | `scripts/debug/operator_recovery_audit.js` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 32 | 1942 | `scripts/debug/probe_source_ocr.ps1` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 23 | 721 | `scripts/debug/publish_test_article.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 28 | 1226 | `scripts/debug/test_article_slug.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 96 | 4006 | `scripts/debug/test_full_nemotron_article.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 22 | 700 | `scripts/debug/test_gemini_api.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 45 | 1867 | `scripts/debug/test_gemini_rest.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 72 | 2363 | `scripts/debug/test_nemotron_stream.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 40 | 1397 | `scripts/debug/test_nvidia_fast.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 47 | 2002 | `scripts/debug/test_nvidia_live_gen.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 33 | 1162 | `scripts/debug/test_nvidia_module.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 53 | 2262 | `scripts/debug/test_nvidia_nemotron.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 23 | 834 | `scripts/debug/test_primp_gemini.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 17 | 778 | `scripts/debug/verify_20.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 43 | 1769 | `scripts/debug/verify_dashboard.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 52 | 2453 | `scripts/debug/verify_live_sites.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| review | scripts | 79 | 2829 | `scripts/debug/verify_nemotron_json.py` | non-production helper retained under scripts/debug or scripts/oneoff |
| ok | scripts | 89 | 3165 | `scripts/dev/check_no_root_scratch.py` |  |
| ok | scripts | 97 | 3698 | `scripts/dev/continue_production_batch.py` |  |
| ok | scripts | 21 | 994 | `scripts/dev/disable_legacy_odysseus_task.ps1` |  |
| ok | scripts | 162 | 5608 | `scripts/dev/live_article_quality_check.py` |  |
| ok | scripts | 11 | 697 | `scripts/dev/live_logs.ps1` |  |
| ok | scripts | 296 | 9256 | `scripts/dev/project_audit.py` |  |
| ok | scripts | 43 | 2399 | `scripts/dev/read_source_image_text.ps1` |  |
| ok | scripts | 520 | 20784 | `scripts/dev/repair_article_quality.py` |  |
| ok | scripts | 323 | 11493 | `scripts/dev/run_production_validation.py` |  |
| ok | scripts | 139 | 5595 | `scripts/dev/runtime_maintenance.py` |  |
| ok | scripts | 212 | 6028 | `scripts/dev/self_clean.py` |  |
| ok | scripts | 146 | 5519 | `scripts/dev/start_agentmemory.ps1` |  |
| ok | scripts | 105 | 4182 | `scripts/dev/start_all_mcp.ps1` |  |
| ok | scripts | 222 | 7399 | `scripts/dev/validate_automation.py` |  |
| ok | scripts | 134 | 4771 | `scripts/dev/validate_gemini_runtime.py` |  |
| ok | scripts | 112 | 3447 | `scripts/ops/backfill_images.py` |  |
| ok | scripts | 78 | 2658 | `scripts/ops/check_pins.py` |  |
| ok | scripts | 94 | 3613 | `scripts/ops/clear_pinterest_drafts.py` |  |
| ok | scripts | 46 | 1432 | `scripts/ops/force_chromium_env.py` |  |
| ok | scripts | 174 | 6551 | `scripts/ops/force_chromium_login.py` |  |
| ok | scripts | 223 | 8020 | `scripts/ops/generate_campaign_pins.py` |  |
| ok | scripts | 141 | 4192 | `scripts/ops/kill_all_processes.py` |  |
| ok | scripts | 79 | 2437 | `scripts/ops/reenqueue_dlq.py` |  |
| ok | scripts | 88 | 3658 | `scripts/ops/reset_and_verify_dashboard.py` |  |
| ok | scripts | 128 | 4839 | `scripts/ops/reset_dashboard_and_roadmaps.py` |  |
| ok | scripts | 96 | 3173 | `scripts/ops/restore_gold_config.py` |  |
| ok | scripts | 59 | 2008 | `scripts/publish_pending_batch.py` |  |
| ok | scripts | 169 | 5177 | `scripts/recover_keywords.py` |  |
| ok | scripts | 37 | 988 | `scripts/start_workers.py` |  |
| ok | scripts | 59 | 2197 | `scripts/sweep_failed.py` |  |
| ok | scripts | 55 | 1955 | `scripts/test_specificity.py` |  |
| ok | tests | 0 | 0 | `tests/__init__.py` |  |
| ok | tests | 44 | 1484 | `tests/conftest.py` |  |
| ok | tests | 0 | 0 | `tests/e2e/__init__.py` |  |
| ok | tests | 0 | 0 | `tests/integration/__init__.py` |  |
| ok | tests | 37 | 1391 | `tests/integration/test_multidomain_routing.py` |  |
| ok | tests | 0 | 0 | `tests/unit/__init__.py` |  |
| ok | tests | 94 | 3087 | `tests/unit/test_ai_engine.py` |  |
| ok | tests | 100 | 4025 | `tests/unit/test_article_quality_policy.py` |  |
| ok | tests | 289 | 10811 | `tests/unit/test_article_remaster_queue.py` |  |
| ok | tests | 170 | 7069 | `tests/unit/test_branding.py` |  |
| ok | tests | 201 | 8719 | `tests/unit/test_browser_utils.py` |  |
| ok | tests | 138 | 4795 | `tests/unit/test_campaign_prompts.py` |  |
| ok | tests | 70 | 3047 | `tests/unit/test_campaign_source_hold.py` |  |
| ok | tests | 90 | 2483 | `tests/unit/test_category_policy.py` |  |
| ok | tests | 98 | 3688 | `tests/unit/test_check_no_root_scratch.py` |  |
| ok | tests | 80 | 3562 | `tests/unit/test_circuit_breaker.py` |  |
| ok | tests | 247 | 11044 | `tests/unit/test_config.py` |  |
| ok | tests | 343 | 13130 | `tests/unit/test_create_hero_image_pollinations.py` |  |
| ok | tests | 86 | 2666 | `tests/unit/test_database_security.py` |  |
| ok | tests | 110 | 3518 | `tests/unit/test_direct_upload_cross_save.py` |  |
| ok | tests | 199 | 9163 | `tests/unit/test_domain.py` |  |
| ok | tests | 111 | 4211 | `tests/unit/test_domain_isolation.py` |  |
| ok | tests | 50 | 1652 | `tests/unit/test_health_monitor.py` |  |
| ok | tests | 475 | 18123 | `tests/unit/test_job_queue_sqlite.py` |  |
| ok | tests | 360 | 12073 | `tests/unit/test_keyword_roadmap.py` |  |
| ok | tests | 88 | 2858 | `tests/unit/test_legacy_article_entrypoints.py` |  |
| ok | tests | 141 | 4429 | `tests/unit/test_log_manager.py` |  |
| ok | tests | 187 | 6325 | `tests/unit/test_mcp_remaster_campaign.py` |  |
| ok | tests | 60 | 2120 | `tests/unit/test_memory_service.py` |  |
| ok | tests | 37 | 1210 | `tests/unit/test_news_scraper.py` |  |
| ok | tests | 18 | 581 | `tests/unit/test_nvidia_fallback.py` |  |
| ok | tests | 162 | 7489 | `tests/unit/test_operator.py` |  |
| ok | tests | 70 | 3093 | `tests/unit/test_operator_client.py` |  |
| ok | tests | 240 | 9353 | `tests/unit/test_operator_live_status.py` |  |
| ok | tests | 1360 | 49137 | `tests/unit/test_operator_pipeline.py` |  |
| ok | tests | 704 | 24612 | `tests/unit/test_pinterest_production_runtime.py` |  |
| ok | tests | 77 | 2335 | `tests/unit/test_pinterest_public_verification.py` |  |
| ok | tests | 78 | 2156 | `tests/unit/test_pipeline_events.py` |  |
| ok | tests | 472 | 19242 | `tests/unit/test_production_batch.py` |  |
| ok | tests | 395 | 18351 | `tests/unit/test_production_batch_import.py` |  |
| ok | tests | 486 | 17131 | `tests/unit/test_production_reconcile.py` |  |
| ok | tests | 253 | 11022 | `tests/unit/test_provisioner.py` |  |
| ok | tests | 165 | 6324 | `tests/unit/test_rate_limiter_persistence.py` |  |
| ok | tests | 375 | 14033 | `tests/unit/test_remaster_deadlines_recovery.py` |  |
| ok | tests | 309 | 10369 | `tests/unit/test_remaster_native_fallback.py` |  |
| ok | tests | 142 | 4819 | `tests/unit/test_remaster_relevance.py` |  |
| ok | tests | 215 | 7953 | `tests/unit/test_remaster_source_quality.py` |  |
| ok | tests | 281 | 10036 | `tests/unit/test_remaster_variants.py` |  |
| ok | tests | 64 | 2546 | `tests/unit/test_runtime_maintenance.py` |  |
| ok | tests | 178 | 7363 | `tests/unit/test_save_image_from_base64.py` |  |
| ok | tests | 122 | 4717 | `tests/unit/test_save_image_from_path.py` |  |
| ok | tests | 25 | 678 | `tests/unit/test_self_clean.py` |  |
| ok | tests | 161 | 6024 | `tests/unit/test_site_factory.py` |  |
| ok | tests | 199 | 7265 | `tests/unit/test_source_image_quality.py` |  |
| ok | tests | 287 | 10275 | `tests/unit/test_startup.py` |  |
| ok | tests | 108 | 3544 | `tests/unit/test_subscribers.py` |  |
| ok | tests | 110 | 4154 | `tests/unit/test_suite_controller.py` |  |
| ok | tests | 32 | 768 | `tests/unit/test_supabase_headers.py` |  |
| ok | tests | 174 | 6050 | `tests/unit/test_supabase_image_upload.py` |  |
| ok | tests | 623 | 22324 | `tests/unit/test_trend_intelligence.py` |  |
| ok | tests | 2216 | 77933 | `tests/unit/test_turbo_articles.py` |  |
| ok | tests | 28 | 902 | `tests/unit/test_windows_compat.py` |  |
