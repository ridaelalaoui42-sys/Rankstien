-- ==========================================
-- RecetaDolce - COMPLETE DATABASE SCHEMA
-- Final Consolidated Version (April 2026)
-- ==========================================

-- 1. CLEANUP (Ensures fresh start for settings to avoid ID type conflicts)
DROP TABLE IF EXISTS settings CASCADE;

-- 2. POSTS TABLE
CREATE TABLE IF NOT EXISTS posts (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  
  -- Core Content
  title TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  content TEXT NOT NULL,
  excerpt TEXT,
  featured_image TEXT,
  image_alt TEXT,
  category TEXT NOT NULL,
  status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
  
  -- Recipe Specifics
  difficulty TEXT DEFAULT 'Media',
  estimated_cost TEXT DEFAULT 'Medio',
  prep_time INTEGER DEFAULT 20,
  cook_time INTEGER DEFAULT 30,
  chef_tip TEXT,
  
  -- SEO & Metadata
  meta_title TEXT,
  meta_description TEXT,
  keywords TEXT[],
  geo_location JSONB,
  recipe_schema JSONB,
  faq_schema JSONB,
  step_images JSONB DEFAULT '[]'::jsonb, -- New: Storage for step-by-step images
  
  -- Metrics
  rating_value FLOAT DEFAULT 0,
  rating_count INTEGER DEFAULT 0
);

-- 3. REVIEWS TABLE
CREATE TABLE IF NOT EXISTS reviews (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT now(),
  post_id UUID REFERENCES posts(id) ON DELETE CASCADE,
  author_name TEXT NOT NULL,
  author_avatar TEXT,
  rating INTEGER CHECK (rating >= 1 AND rating <= 5),
  content TEXT NOT NULL,
  status TEXT DEFAULT 'approved' CHECK (status IN ('pending', 'approved', 'rejected'))
);

-- 4. SETTINGS TABLE (Optimized with TEXT ID for 'global' singleton)
CREATE TABLE settings (
  id TEXT PRIMARY KEY DEFAULT 'global',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  
  -- General
  site_name TEXT DEFAULT 'RecetaDolce',
  site_description TEXT,
  site_logo TEXT,
  contact_email TEXT,
  
  -- Analytics & Tracking
  google_analytics_id TEXT,
  custom_head_code TEXT,
  custom_footer_code TEXT,
  
  -- Navigation & Structure
  navigation_menu JSONB DEFAULT '[]'::jsonb,
  categories TEXT[] DEFAULT '{}'::text[],
  
  -- SEO & Ads
  seo_keywords TEXT[],
  ads_enabled BOOLEAN DEFAULT false,
  adsense_client_id TEXT,
  ads_top_slot TEXT,
  ads_middle_slot TEXT,
  ads_bottom_slot TEXT,
  ads_sidebar_slot TEXT,
  
  -- Social Media
  facebook_url TEXT,
  instagram_url TEXT,
  pinterest_url TEXT,
  twitter_url TEXT,
  youtube_url TEXT,
  tiktok_url TEXT
);

-- 5. NEWSLETTER SUBSCRIBERS
CREATE TABLE IF NOT EXISTS subscribers (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT now(),
  email TEXT UNIQUE NOT NULL
);

-- 6. COMMENTS TABLE
CREATE TABLE IF NOT EXISTS comments (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT now(),
  post_id UUID REFERENCES posts(id) ON DELETE CASCADE,
  author_name TEXT NOT NULL,
  content TEXT NOT NULL,
  parent_id UUID REFERENCES comments(id) ON DELETE CASCADE
);

-- ==========================================
-- SECURITY: ROW LEVEL SECURITY (RLS)
-- ==========================================

ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscribers ENABLE ROW LEVEL SECURITY;
ALTER TABLE comments ENABLE ROW LEVEL SECURITY;

-- Posts Policies
DROP POLICY IF EXISTS "Public read for published posts" ON posts;
DROP POLICY IF EXISTS "Admin full access for posts" ON posts;
CREATE POLICY "Public read for published posts" ON posts FOR SELECT USING (status = 'published');
CREATE POLICY "Admin full access for posts" ON posts FOR ALL USING (true); 

-- Reviews Policies
DROP POLICY IF EXISTS "Public read for approved reviews" ON reviews;
DROP POLICY IF EXISTS "Public insert for reviews" ON reviews;
DROP POLICY IF EXISTS "Admin full access for reviews" ON reviews;
CREATE POLICY "Public read for approved reviews" ON reviews FOR SELECT USING (status = 'approved');
CREATE POLICY "Public insert for reviews" ON reviews FOR INSERT WITH CHECK (true);
CREATE POLICY "Admin full access for reviews" ON reviews FOR ALL USING (true);

-- Settings Policies
DROP POLICY IF EXISTS "Public read for settings" ON settings;
DROP POLICY IF EXISTS "Admin full access for settings" ON settings;
CREATE POLICY "Public read for settings" ON settings FOR SELECT USING (true);
CREATE POLICY "Admin full access for settings" ON settings FOR ALL USING (true);

-- Subscribers Policies
DROP POLICY IF EXISTS "Public insert for subscribers" ON subscribers;
DROP POLICY IF EXISTS "Admin full access for subscribers" ON subscribers;
CREATE POLICY "Public insert for subscribers" ON subscribers FOR INSERT WITH CHECK (true);
CREATE POLICY "Admin full access for subscribers" ON subscribers FOR ALL USING (true);

-- Comments Policies
DROP POLICY IF EXISTS "Public read for comments" ON comments;
DROP POLICY IF EXISTS "Public insert for comments" ON comments;
DROP POLICY IF EXISTS "Admin full access for comments" ON comments;
CREATE POLICY "Public read for comments" ON comments FOR SELECT USING (true);
CREATE POLICY "Public insert for comments" ON comments FOR INSERT WITH CHECK (true);
CREATE POLICY "Admin full access for comments" ON comments FOR ALL USING (true);

-- ==========================================
-- FUNCTIONS & SEED DATA
-- ==========================================

-- Rating Function
CREATE OR REPLACE FUNCTION increment_rating(p_post_id UUID, p_new_rating FLOAT)
RETURNS VOID AS $$
BEGIN
  UPDATE posts
  SET rating_value = rating_value + p_new_rating,
      rating_count = rating_count + 1
  WHERE id = p_post_id;
END;
$$ LANGUAGE plpgsql;

-- Insert default settings
INSERT INTO settings (id, site_name, site_description)
VALUES ('global', 'RecetaDolce', 'Auténticas recetas de cocina española con un toque editorial.')
ON CONFLICT (id) DO UPDATE SET site_name = EXCLUDED.site_name;
