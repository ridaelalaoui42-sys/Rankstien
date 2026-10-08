# System Architecture

Updated: 2026-10-06

RankStein is a local-first, multi-tenant autonomous publishing and social syndication ecosystem. Hermes Codex generates researched Spanish culinary content, MCP servers expose tool interfaces, Python services execute domain and campaign logic, Playwright controls unattended Chromium browser sessions, Supabase stores articles and media, and AgentMemory tracks durable operational lessons.

---

## 1. Multi-Tier Process Topology & Port Mapping (C4 Container Model)

This diagram details the actual process boundaries, network protocols, IPC interfaces, and listening ports across the local Windows host and external clouds.

```mermaid
flowchart TB
    subgraph Host ["Windows Production Host (Local-First Runtime)"]
        subgraph OrchestrationTier ["Orchestration & Control Plane"]
            Scheduler["Windows Task Scheduler\n(start_all_services.ps1)"]
            CLI["RankStein Master CLI\n(rankstein.py launch / run)"]
            FastMCP["RankStein FastMCP Server\n(rankstein_mcp_server.py / 54 Tools)"]
        end

        subgraph UIEngine ["Operator & Gateway Daemons"]
            Frontend["RankStein Operator\n127.0.0.1:7000/operator\n(Independent FastAPI Control Plane)"]
            HermesCodex["Hermes Codex Gateway\n127.0.0.1:8642 /v1\n(OpenAI API Compatible)"]
            LegacyProxy["Optional Legacy Model Proxy\n127.0.0.1:8000\n(Not an Operator Dependency)"]
            AgentMem["AgentMemory Daemon\n127.0.0.1:3111\n(BM25 + 384d Vector + Graph)"]
            III["iii-engine\nws://127.0.0.1:49134"]
        end

        subgraph WorkerCluster ["Autonomous Worker Pool"]
            ArticleWorker["TurboArticles Worker\n(backend/scripts/turbo_articles.py)"]
            RemasterWorker["Remaster Campaign Worker\n(backend/services/remasterer.py)"]
            SupervisorDaemon["Autonomous Supervisor\n(run_autonomous.py / PID Lease)"]
            BrowserPool["Playwright Chromium Pool\n(Isolated User Data Profiles)"]
        end

        subgraph LocalState ["Local Persistent State (WAL & Markdown)"]
            JobsDB[("SQLite Queue DB\ndata/queue/jobs.db (WAL)")]
            RanksteinDB[("Registry DB\ndata/rankstein.db")]
            Roadmaps[("Keyword Roadmaps\ndata/domains/*/keywords.md")]
            MediaStorage["Disk Media Cache\ndata/media/remaster_final/"]
        end
    end

    subgraph ExternalClouds ["External Cloud Services"]
        SupabaseAPI["Supabase REST API\n(PostgreSQL multi-tenant)"]
        SupabaseBucket["Supabase Storage Buckets\n(images/ & heroes/)"]
        PinterestWeb["Pinterest Platform\n(es.pinterest.com / Business Accounts)"]
        GoogleSignals["Google APIs & RSS\n(Trends, News, Autocomplete)"]
    end

    Scheduler --> CLI
    CLI --> FastMCP
    FastMCP <--> AgentMem
    AgentMem <--> III
    CLI --> ArticleWorker
    CLI --> SupervisorDaemon

    ArticleWorker --> HermesCodex
    ArticleWorker --> Roadmaps
    ArticleWorker --> RanksteinDB
    ArticleWorker --> SupabaseAPI
    ArticleWorker --> SupabaseBucket
    ArticleWorker --> RemasterWorker

    RemasterWorker --> BrowserPool
    RemasterWorker --> MediaStorage
    RemasterWorker --> JobsDB

    SupervisorDaemon --> JobsDB
    SupervisorDaemon --> BrowserPool
    BrowserPool --> PinterestWeb

    CLI --> GoogleSignals
    Frontend --> SupabaseAPI
```

---

## 2. End-to-End Keyword-to-Live Content Lifecycle State Machine

This state machine defines the qualification gates, extraction rules, and fail-closed transitions required before a keyword can enter production or reach `Live` status.

```mermaid
stateDiagram-v2
    [*] --> Discovered: Multi-Source Scraping (Pinterest, News, RSS)
    
    state "Discovery & Qualification" as Phase1 {
        Discovered --> SpecificityCheck: Dish specificity score
        SpecificityCheck --> Rejected: Category-only (e.g. 'comida facil')
        SpecificityCheck --> DemandCheck: Demand Score >= 2
        DemandCheck --> Rejected: Zero Google search volume
        DemandCheck --> Qualified: Corroborated demand
        Qualified --> Pending: Appended to keywords.md
    }

    state "Article Production (Fail-Closed)" as Phase2 {
        Pending --> InProgress: Lease keyword
        InProgress --> ScrapingSources: scrape_news_sources()
        ScrapingSources --> Failed: < 2 Valid recipe sources
        ScrapingSources --> CompactNotes: extract_article_content()
        CompactNotes --> LLMGeneration: Hermes Codex (gpt-5.6-sol)
        LLMGeneration --> Failed: LLM Provider Failure / Timeout
        LLMGeneration --> QualityAudit: validate_article_quality()
        QualityAudit --> LLMGeneration: Retry up to 3x (Anti-AI / Schema missing)
        QualityAudit --> ArticleApproved: Rich recipe schema validated
    }

    state "Creative Assets & Cloud Sync" as Phase3 {
        ArticleApproved --> HeroCreation: create_hero_image_codex()
        HeroCreation --> Failed: Non-Codex / Placeholder returned
        HeroCreation --> ExifInjection: Canon EOS 5D + GPS Madrid/Bcn
        ExifInjection --> SupabaseStorage: upload_image_to_supabase()
        SupabaseStorage --> PrimaryPin: create_article_pin() (2:3)
        PrimaryPin --> Priority1Upload: Direct upload via Supervisor
        Priority1Upload --> NeedsVerification: Pin ID unconfirmed
        Priority1Upload --> SupabasePublish: publish_article_to_supabase()
    }

    state "Remaster Studio & Live Verification" as Phase4 {
        SupabasePublish --> RemasterCampaign: run_article_remaster_campaign()
        RemasterCampaign --> ScrapePinterest: 15 Unique pin sources
        ScrapePinterest --> GenerateVariants: 15 x (viral_visual + recipe_card)
        GenerateVariants --> Enqueue30: Enqueue 30 jobs in jobs.db
        Enqueue30 --> Live: All 30 jobs proven + Verified Primary Pin
    }

    Rejected --> [*]
    Failed --> [*]
    NeedsVerification --> [*]
    Live --> [*]
```

---

## 3. The 30-Pin Remaster Studio Pipeline

This flowchart documents the atomic pair generation and deterministic typography engine that transforms 15 unique scraped Pinterest sources into 30 luxury pins.

```mermaid
flowchart TD
    ArticleData["Published Article Data\n(Title, Ingredients, Instructions, Domain Handle)"] --> BriefBuilder["Scrape Brief Generator\n(core_terms, expected_terms, blocked_terms)"]

    subgraph PinterestScrape ["1. Stealth Image Ingestion"]
        BriefBuilder --> StealthBrowser["Playwright Stealth Scraper\n(Pinterest Grid Search)"]
        StealthBrowser --> Dedupe["Pin ID Deduplicator"]
        Dedupe --> DimensionFilter{"Resolution Check\nWidth >= 500\nHeight >= 700?"}
        DimensionFilter -- No --> Discard["Discard Asset"]
        DimensionFilter -- Yes --> RelevanceScorer{"Relevance Score >= 2\n(Food context matches dish)?"}
        RelevanceScorer -- No --> Discard
        RelevanceScorer -- Yes --> AcceptedSources["Target: Exactly 15 Unique Sources"]
    end

    subgraph PairedCompositor ["2. Paired Pin Studio (Deterministic Pillow Compositor)"]
        AcceptedSources --> SourceLoop["For Each Unique Source (1..15)"]
        
        SourceLoop --> VisualWorker["Variant A: viral_visual\n(1000x1500 Vertical)\n- Photo-led save/click hook\n- Domain brand palette & typography\n- Short badge & CTA button"]
        
        SourceLoop --> CardWorker["Variant B: recipe_card\n(1000x1500 Vertical)\n- 50% Hero photo header\n- Real recipe ingredients list\n- Numbered preparation steps\n- Chef tips & brand URL"]
        
        VisualWorker & CardWorker --> PairIntegrity{"Are Both Variants\nPresent & Valid?"}
        PairIntegrity -- No --> DropPair["Drop Incomplete Pair\n(Fail Atomic Unit)"]
        PairIntegrity -- Yes --> ValidPair["Retain Complete Pair (pair_id)"]
    end

    subgraph EnqueueStage ["3. Atomic Batch Enqueue"]
        ValidPair --> TotalCheck{"Total Valid Assets == 30\n(15 Unique Sources x 2)?"}
        TotalCheck -- No --> AbortCampaign["Abort & Report Incomplete\n(Mutates zero queue jobs)"]
        TotalCheck -- Yes --> ExifBatch["Inject EXIF Culinary Metadata"]
        ExifBatch --> SaveFinal["Save to data/media/remaster_final/"]
        SaveFinal --> EnqueueJobs["Atomic Enqueue to SQLite jobs.db\n(30 Unique Jobs with account_handle)"]
        EnqueueJobs --> CampaignReport["Write data/reports/campaigns/*_remaster_*.json"]
    end
```

---

## 4. Autonomous Pinterest Supervisor & Self-Healing Loop

This sequence diagram details unattended Pinterest automation, singleton leasing, account-level serialization, rate budgeting, and automated draft-clearing.

```mermaid
sequenceDiagram
    autonumber
    participant Sup as Autonomous Supervisor
    participant State as Runtime Lease (campaign_lease.json)
    participant Queue as SQLite Queue (jobs.db)
    participant Rate as RateLimiter & CircuitBreaker
    participant Pool as Chromium SessionPool
    participant Driver as Playwright PinterestDriver
    participant SelfHeal as Self-Healing Engine

    Note over Sup, State: Step 1: Singleton Lease & Heartbeat
    Sup->>State: Acquire PID Lease & write heartbeat (every 1s)
    
    Note over Sup, Queue: Step 2: Atomic Dequeue
    Sup->>Queue: BEGIN IMMEDIATE dequeue(batch=2, order_by=priority ASC)
    Queue-->>Sup: Returns leased Jobs (Priority 1 primary pins first)

    loop For Each Leased Job
        Note over Sup, Rate: Step 3: Account-Level Budget Guard
        Sup->>Rate: Check account limits (20/hr, 500/day, circuit closed?)
        alt Rate Limit Exceeded or Circuit Tripped
            Rate-->>Sup: Tripped / Cooldown Active
            Sup->>Queue: Release lease & reschedule with exponential backoff
        else Budget Available
            Rate-->>Sup: Approved
            Sup->>Pool: Acquire lock for account_handle (asyncio.Lock)
            Pool->>Driver: Launch/Reuse Chromium Profile

            Note over Driver, SelfHeal: Step 4: Pin Creation & Self-Healing
            Driver->>Driver: Navigate to pin-builder
            alt Pin Editor Disabled (Pinterest 50-Draft Limit)
                Driver->>SelfHeal: Detect draft stall
                SelfHeal->>SelfHeal: Run clear_pinterest_drafts.py
                SelfHeal-->>Driver: Drafts cleared
                Driver->>Driver: Reload pin-builder
            end

            Driver->>Driver: Upload image & fill Title, Description, Link
            Driver->>Driver: Select Board ('Simplified Pick First' logic)
            Driver->>Driver: Click 'Publish Now' (Fallback: Ctrl+Enter)
            
            alt Verified pin_id or pin_url captured within 8s
                Driver-->>Sup: Success (pin_id: 123456789)
                Sup->>Queue: mark_completed(job_id)
                Sup->>Rate: Record success
            else Timeout or Selector Exception
                Driver-->>Sup: Failure Exception
                Sup->>Rate: Record failure streak
                alt Attempts < 3
                    Sup->>Queue: mark_retry(job_id, backoff_seconds)
                else Attempts >= 3
                    Sup->>Queue: move_to_dead_letter_queue(job_id, reason)
                end
            end
            Sup->>Pool: Release account lock
        end
    end
```

---

## 5. Multi-Tenant Domain Partitioning & Isolation Matrix

This entity-relationship model defines how the Domain Registry (`rankstein/domain.py`) guarantees multi-tenant isolation across all system resources.

```mermaid
erDiagram
    DOMAIN_REGISTRY ||--o{ DOMAIN_ENTITY : registers
    DOMAIN_ENTITY ||--|| BRANDING_PROFILE : defines
    DOMAIN_ENTITY ||--|| SUPABASE_CREDENTIALS : authenticates
    DOMAIN_ENTITY ||--|| PINTEREST_ACCOUNT : binds
    DOMAIN_ENTITY ||--o{ KEYWORD_ROADMAP : owns
    DOMAIN_ENTITY ||--o{ REMASTER_BATCH : isolates

    DOMAIN_ENTITY {
        string handle PK "e.g. recetadolce / recetagenial"
        string public_domain "recetadolce.com / recetagenial.com"
        string language "es"
        string niche "Alta Pasteleria vs Tradicional Espanola"
        int daily_pin_budget "50 vs 25"
    }

    BRANDING_PROFILE {
        string primary_color "#D4AF37 (Gold) vs #C67B3C (Rust)"
        string accent_color "#2C3E50 (Charcoal) vs #7A8B5C (Sage)"
        string brand_name_short "RECETA DOLCE vs RECETA GENIAL"
        string cta_text "TOCA PARA VER LA RECETA vs GUARDA ESTA RECETA"
    }

    SUPABASE_CREDENTIALS {
        string supabase_url "xjvmnmfczvwkjiasirsl vs hokcljsrrnjxzgdhjice"
        secret service_role_key "Encrypted in process memory"
        string storage_bucket "heroes and inline images"
    }

    PINTEREST_ACCOUNT {
        string account_handle "rida vs media"
        string profile_path "data/sessions/pinterest_*"
        json boards_default "Chocolate, Fresas vs Arroces, Carnes, ENSALADES"
    }

    KEYWORD_ROADMAP {
        string file_path "data/domains/<handle>/keywords.md"
        int live_count "550 vs 326"
        int pending_count "119 vs 126"
        string status "Pending, Live, Needs Verification, Failed"
    }

    REMASTER_BATCH {
        string session_profile "remasterer_<handle>"
        string report_path "data/reports/campaigns/<handle>_*.json"
        string output_dir "data/media/remaster_final/<handle>/"
    }
```

---

## 6. Core Component Reference

| Layer | Primary Source Files | Core Responsibility |
|---|---|---|
| **CLI & Suite Control** | `rankstein.py`, `rankstein/cli.py`, `rankstein/launcher.py` | Full-service preflight, health checks, domain administration, and service bootstrapping. |
| **Domain Registry** | `rankstein/domain.py`, `data/domains/` | Multi-tenant isolation for credentials, palettes, branding tokens, categories, and roadmaps. |
| **Trend Discovery** | `rankstein/trend_intelligence.py` | Gathers candidate recipe trends, enforces dish specificity, and validates search demand depth. |
| **Article Worker** | `backend/scripts/turbo_articles.py` | Scrapes 2+ recipe sources, queries Hermes Codex (`gpt-5.6-sol`), enforces Schema.org recipe JSON, and publishes to Supabase. |
| **Quality Validator** | `backend/services/quality_evaluator.py` | Rejects template text, missing ingredients/instructions, AI boilerplate, and unformatted lists. |
| **Hero Image Engine** | `backend/scripts/hero_image_pipeline.py` | Generates photorealistic 16:9 hero images with Codex `gpt-image-2`, injects EXIF metadata, and uploads to cloud storage. |
| **30-Pin Remasterer** | `backend/services/remasterer.py`, `rankstein/remaster_variants.py` | Scrapes 15 unique dish-relevant Pinterest pins and outputs paired 1000x1500 assets (`viral_visual` and `recipe_card`). |
| **Job Queue** | `pinterest_automation/job_queue.py` | SQLite WAL-backed queue with atomic `BEGIN IMMEDIATE` dequeuing, priority levels, and Dead Letter Queue (DLQ). |
| **Supervisor & Driver** | `pinterest_automation/supervisor.py`, `pinterest_automation/pinterest_driver.py` | Unattended Playwright Chromium automation with profile isolation, account locks, rate limits, and draft auto-clearing. |
| **Memory & Tool API** | `rankstein_mcp_server.py`, `scripts/dev/start_agentmemory.ps1` | 54 FastMCP tools and hybrid triple-stream memory engine storing operational lessons and telemetry. |

---

## 7. Non-Negotiable Operational Invariants

1. **Fail-Closed on Non-LLM Text:** No article may be published from deterministic, mock, or template text. If LLM providers fail, the keyword is marked `Failed` and halts.
2. **Strict Recipe Schema:** `recipeIngredient` and `recipeInstructions` arrays must never be empty.
3. **Atomic 30-Pin Remaster Target:** Remaster campaigns must yield exactly 15 unique sources and 30 paired assets (`viral_visual` + `recipe_card`). If fewer survive, zero jobs are enqueued.
4. **Verified `Live` Criteria:** A keyword is marked `Live` **only** when Supabase publish, hero storage, verified primary `pin_id` / `pin_url`, and the 30-pin remaster enqueue all succeed.
5. **Chromium Exclusivity:** Unattended Pinterest automation runs exclusively on Chromium to avoid Firefox lock stalls.
6. **Account Concurrency Limit:** Exactly one active browser session per Pinterest account handle at any given moment.
