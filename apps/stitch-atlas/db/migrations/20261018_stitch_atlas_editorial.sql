-- Stitch Atlas: APPLY ONLY TO A NEW, DEDICATED SUPABASE PROJECT.
-- This does not belong in RecetaDolce/RecetaGenial's production databases.
-- No staff identities or publication privileges are invented by this migration.
BEGIN;

CREATE TABLE public.craft_staff (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK(role IN ('contributor','editor','publisher')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.craft_settings (
  singleton bool PRIMARY KEY DEFAULT true CHECK (singleton),
  publishing_enabled bool NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.craft_settings(singleton,publishing_enabled) VALUES (true,false);

CREATE TABLE public.craft_posts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  title text NOT NULL CHECK(length(title) BETWEEN 6 AND 180),
  description text NOT NULL DEFAULT '',
  body text NOT NULL DEFAULT '',
  kind text NOT NULL CHECK(kind IN ('pattern','tutorial','stitch_guide','roundup')),
  category text NOT NULL CHECK(category IN ('bags','stitches','beginners','home','accessories','amigurumi','seasonal')),
  status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','in_review','needs_changes','approved','published','archived')),
  content_rights text NOT NULL DEFAULT 'unverified' CHECK(content_rights IN ('unverified','original','licensed')),
  terminology text CHECK(terminology IN ('US','UK')),
  images jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(images) = 'array'),
  steps jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(steps) = 'array'),
  materials jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(materials) = 'array'),
  source_links jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(source_links) = 'array'),
  stitch_count_checks jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(stitch_count_checks) = 'array'),
  test_evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(test_evidence) = 'object'),
  hook_size_mm text NOT NULL DEFAULT '',
  yarn_weight text NOT NULL DEFAULT '',
  gauge text NOT NULL DEFAULT '',
  finished_dimensions text NOT NULL DEFAULT '',
  seo_keyword text NOT NULL DEFAULT '',
  research_evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(research_evidence) = 'object'),
  author_id uuid NOT NULL REFERENCES auth.users(id),
  reviewed_by uuid REFERENCES auth.users(id),
  reviewer_notes text NOT NULL DEFAULT '',
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT no_fake_craft_media CHECK (
    (coalesce(title,'') || ' ' || coalesce(description,'') || ' ' || coalesce(body,'') || ' ' ||
     coalesce(images::text,'') || ' ' || coalesce(steps::text,'') || ' ' || coalesce(source_links::text,'') || ' ' ||
     coalesce(test_evidence::text,'') || ' ' || coalesce(seo_keyword,'')) !~* 
    '(example[.](com|org|net)|via[.]placeholder[.]com|placehold[.]co|dummyimage[.]com|recetagenial|recetadolce)'
  )
);
CREATE INDEX craft_posts_public_idx ON public.craft_posts(status, published_at DESC) WHERE status='published';
CREATE INDEX craft_posts_editorial_idx ON public.craft_posts(updated_at DESC);

CREATE TABLE public.craft_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  post_id uuid NOT NULL REFERENCES public.craft_posts(id) ON DELETE CASCADE,
  actor_id uuid NOT NULL REFERENCES auth.users(id),
  action text NOT NULL CHECK(action IN ('submitted','approved','changes_requested','published','archived')),
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX craft_events_post_idx ON public.craft_events(post_id, created_at DESC);

CREATE FUNCTION public.craft_role() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT s.role FROM public.craft_staff s WHERE s.user_id = auth.uid() LIMIT 1;
$$;

CREATE FUNCTION public.craft_release_blockers(p public.craft_posts) RETURNS text[]
LANGUAGE plpgsql STABLE SET search_path = '' AS $$
DECLARE issues text[] := ARRAY[]::text[];
DECLARE image jsonb; DECLARE row_check jsonb;
DECLARE found_image boolean := false;
DECLARE rows_valid boolean := true;
BEGIN
  IF length(trim(p.title)) < 15 THEN issues := array_append(issues,'TITLE_TOO_SHORT'); END IF;
  IF length(trim(p.description)) < 65 THEN issues := array_append(issues,'DESCRIPTION_TOO_SHORT'); END IF;
  IF length(trim(p.body)) < 600 THEN issues := array_append(issues,'SUBSTANTIVE_BODY_REQUIRED'); END IF;
  IF p.content_rights NOT IN ('original','licensed') THEN issues := array_append(issues,'CONTENT_RIGHTS_REQUIRED'); END IF;
  IF p.kind <> 'roundup' THEN
    IF jsonb_array_length(p.steps) < 3 OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.steps) step_text WHERE length(trim(step_text))<15) THEN issues := array_append(issues,'COMPLETE_STEPS_REQUIRED'); END IF;
    IF p.terminology IS NULL THEN issues := array_append(issues,'CROCHET_TERMINOLOGY_REQUIRED'); END IF;
  ELSE
    IF jsonb_array_length(p.source_links)<2 OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.source_links) source_url WHERE source_url !~ '^https://[^[:space:]]+[.]') THEN issues := array_append(issues,'ROUNDUP_SOURCES_REQUIRED'); END IF;
  END IF;
  FOR image IN SELECT value FROM jsonb_array_elements(p.images) LOOP
    IF image->>'url' ~ '^https://[^[:space:]]+[.]' AND
       length(trim(coalesce(image->>'alt',''))) >= 10 AND
       (image->>'rights_verified') = 'true' AND
       (image->>'rights_type') IN ('original','licensed') THEN found_image := true; END IF;
  END LOOP;
  IF NOT found_image THEN issues := array_append(issues,'LICENSED_ORIGINAL_IMAGE_REQUIRED'); END IF;
  IF p.kind = 'pattern' THEN
    IF jsonb_array_length(p.materials)<2 OR trim(p.hook_size_mm)='' OR trim(p.yarn_weight)='' OR trim(p.gauge)='' OR trim(p.finished_dimensions)='' THEN
      issues := array_append(issues,'PATTERN_MATERIALS_GAUGE_DIMENSIONS_REQUIRED'); END IF;
    IF p.test_evidence->>'test_status' IS DISTINCT FROM 'physically_tested'
      OR p.test_evidence->>'human_attested' IS DISTINCT FROM 'true'
      OR length(trim(coalesce(p.test_evidence->>'tester_name',''))) < 3
      OR length(trim(coalesce(p.test_evidence->>'test_notes',''))) < 40
      OR coalesce(p.test_evidence->>'prototype_photo_url','') !~ '^https://[^[:space:]]+[.]'
    THEN issues := array_append(issues,'INDEPENDENT_PHYSICAL_TEST_EVIDENCE_REQUIRED'); END IF;
    IF jsonb_array_length(p.stitch_count_checks)<1 THEN rows_valid := false; END IF;
    FOR row_check IN SELECT value FROM jsonb_array_elements(p.stitch_count_checks) LOOP
      IF NOT (
        coalesce(row_check->>'start','') ~ '^[0-9]+$'
        AND coalesce(row_check->>'increases','') ~ '^[0-9]+$'
        AND coalesce(row_check->>'decreases','') ~ '^[0-9]+$'
        AND coalesce(row_check->>'end','') ~ '^[0-9]+$'
      ) THEN rows_valid := false;
      ELSIF (row_check->>'start')::numeric <= 0 OR
        (row_check->>'start')::numeric + (row_check->>'increases')::numeric - (row_check->>'decreases')::numeric <> (row_check->>'end')::numeric
      THEN rows_valid := false; END IF;
    END LOOP;
    IF NOT rows_valid THEN issues := array_append(issues,'STITCH_COUNT_MATH_REQUIRED'); END IF;
  END IF;
  RETURN issues;
END;
$$;

CREATE FUNCTION public.craft_touch_updated_at() RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;
CREATE TRIGGER craft_posts_updated_at BEFORE UPDATE ON public.craft_posts
  FOR EACH ROW EXECUTE FUNCTION public.craft_touch_updated_at();

CREATE FUNCTION public.craft_submit_post(p_post_id uuid) RETURNS public.craft_posts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE item public.craft_posts;
BEGIN
  SELECT * INTO item FROM public.craft_posts WHERE id = p_post_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Post not found' USING ERRCODE='P0002'; END IF;
  IF item.author_id IS DISTINCT FROM auth.uid() OR public.craft_role() IS NULL THEN RAISE EXCEPTION 'Not authorized' USING ERRCODE='42501'; END IF;
  IF item.status NOT IN ('draft','needs_changes') THEN RAISE EXCEPTION 'Only drafts may be submitted'; END IF;
  IF length(trim(item.description)) < 25 OR length(trim(item.body)) < 200 THEN RAISE EXCEPTION 'Draft needs a summary and meaningful original text'; END IF;
  UPDATE public.craft_posts SET status='in_review',reviewed_by=NULL,reviewer_notes='' WHERE id=p_post_id RETURNING * INTO item;
  INSERT INTO public.craft_events(post_id,actor_id,action) VALUES (item.id,auth.uid(),'submitted');
  RETURN item;
END $$;

CREATE FUNCTION public.craft_review_post(p_post_id uuid,p_decision text,p_notes text DEFAULT '') RETURNS public.craft_posts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE item public.craft_posts; DECLARE issues text[];
BEGIN
  IF public.craft_role() NOT IN ('editor','publisher') THEN RAISE EXCEPTION 'Reviewer role required' USING ERRCODE='42501'; END IF;
  SELECT * INTO item FROM public.craft_posts WHERE id=p_post_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Post not found' USING ERRCODE='P0002'; END IF;
  IF item.author_id=auth.uid() THEN RAISE EXCEPTION 'Independent reviewer required' USING ERRCODE='42501'; END IF;
  IF item.status <> 'in_review' THEN RAISE EXCEPTION 'Only submitted posts can be reviewed'; END IF;
  IF p_decision NOT IN ('approve','request_changes') THEN RAISE EXCEPTION 'Invalid review action'; END IF;
  IF p_decision='approve' THEN
    issues := public.craft_release_blockers(item);
    IF cardinality(issues)>0 THEN RAISE EXCEPTION 'Quality gate: %', array_to_string(issues,','); END IF;
    UPDATE public.craft_posts SET status='approved',reviewed_by=auth.uid(),reviewer_notes=left(coalesce(p_notes,''),4000) WHERE id=p_post_id RETURNING * INTO item;
  ELSE
    IF length(trim(coalesce(p_notes,'')))<15 THEN RAISE EXCEPTION 'Explain requested changes'; END IF;
    UPDATE public.craft_posts SET status='needs_changes',reviewed_by=auth.uid(),reviewer_notes=left(p_notes,4000) WHERE id=p_post_id RETURNING * INTO item;
  END IF;
  INSERT INTO public.craft_events(post_id,actor_id,action,note) VALUES (item.id,auth.uid(),CASE WHEN p_decision='approve' THEN 'approved' ELSE 'changes_requested' END,left(coalesce(p_notes,''),4000));
  RETURN item;
END $$;

CREATE FUNCTION public.craft_publish_post(p_post_id uuid) RETURNS public.craft_posts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE item public.craft_posts; DECLARE issues text[];
BEGIN
  IF public.craft_role() <> 'publisher' THEN RAISE EXCEPTION 'Publisher role required' USING ERRCODE='42501'; END IF;
  IF NOT (SELECT publishing_enabled FROM public.craft_settings WHERE singleton=true) THEN RAISE EXCEPTION 'Publication remains disabled'; END IF;
  SELECT * INTO item FROM public.craft_posts WHERE id=p_post_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Post not found' USING ERRCODE='P0002'; END IF;
  IF item.status <> 'approved' OR item.reviewed_by IS NULL OR item.reviewed_by = item.author_id THEN RAISE EXCEPTION 'Independent approval required'; END IF;
  issues:=public.craft_release_blockers(item);
  IF cardinality(issues)>0 THEN RAISE EXCEPTION 'Quality gate: %',array_to_string(issues,','); END IF;
  UPDATE public.craft_posts SET status='published',published_at=now() WHERE id=p_post_id RETURNING * INTO item;
  INSERT INTO public.craft_events(post_id,actor_id,action) VALUES (item.id,auth.uid(),'published');
  RETURN item;
END $$;

CREATE FUNCTION public.craft_archive_post(p_post_id uuid) RETURNS public.craft_posts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE item public.craft_posts;
BEGIN
  IF public.craft_role()<>'publisher' THEN RAISE EXCEPTION 'Publisher role required' USING ERRCODE='42501'; END IF;
  SELECT * INTO item FROM public.craft_posts WHERE id=p_post_id FOR UPDATE;
  IF NOT FOUND OR item.status <> 'published' THEN RAISE EXCEPTION 'Only published articles can be archived'; END IF;
  UPDATE public.craft_posts SET status='archived' WHERE id=p_post_id RETURNING * INTO item;
  INSERT INTO public.craft_events(post_id,actor_id,action) VALUES (item.id,auth.uid(),'archived');
  RETURN item;
END $$;

ALTER TABLE public.craft_staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.craft_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.craft_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.craft_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY craft_staff_self_read ON public.craft_staff FOR SELECT TO authenticated USING (user_id=auth.uid());
CREATE POLICY craft_public_posts ON public.craft_posts FOR SELECT TO anon,authenticated USING(status='published');
CREATE POLICY craft_staff_posts ON public.craft_posts FOR SELECT TO authenticated USING(public.craft_role() IS NOT NULL);
CREATE POLICY craft_contributor_insert ON public.craft_posts FOR INSERT TO authenticated WITH CHECK(
  public.craft_role() IS NOT NULL AND author_id=auth.uid() AND status='draft'
);
CREATE POLICY craft_contributor_edit ON public.craft_posts FOR UPDATE TO authenticated USING(
  public.craft_role() IS NOT NULL AND author_id=auth.uid() AND status IN ('draft','needs_changes')
) WITH CHECK(author_id=auth.uid() AND status IN ('draft','needs_changes'));
CREATE POLICY craft_events_staff_read ON public.craft_events FOR SELECT TO authenticated USING(public.craft_role() IS NOT NULL);

-- Even authenticated members cannot directly publish or write audit events.
REVOKE ALL ON public.craft_staff, public.craft_settings, public.craft_posts, public.craft_events FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.craft_posts TO anon;
GRANT SELECT,INSERT,UPDATE ON public.craft_posts TO authenticated;
GRANT SELECT ON public.craft_staff,public.craft_events TO authenticated;
REVOKE ALL ON FUNCTION public.craft_role() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.craft_role() TO authenticated;
REVOKE ALL ON FUNCTION public.craft_release_blockers(public.craft_posts) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.craft_release_blockers(public.craft_posts) TO authenticated;
REVOKE ALL ON FUNCTION public.craft_submit_post(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.craft_review_post(uuid,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.craft_publish_post(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.craft_archive_post(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.craft_submit_post(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.craft_review_post(uuid,text,text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.craft_publish_post(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.craft_archive_post(uuid) TO authenticated;

COMMENT ON TABLE public.craft_posts IS 'Stitch Atlas only: independent free crochet craft editorial data; NOT cooking Recipe markup';
COMMENT ON TABLE public.craft_settings IS 'Publishing disabled by default. Explicitly enable only after original content, domain and moderation approval.';
COMMIT;
