/** Pure validation for Stitch Atlas. Drafts may be incomplete; release never is. */
export const KINDS = ['pattern', 'tutorial', 'stitch_guide', 'roundup'];
export const CATEGORIES = ['bags', 'stitches', 'beginners', 'home', 'accessories', 'amigurumi', 'seasonal'];
export const STATUS = ['draft', 'in_review', 'needs_changes', 'approved', 'published', 'archived'];
const reservedHost = /https?:\/\/(?:[a-z\d-]+\.)*(?:example\.(?:com|net|org)|placehold\.co|dummyimage\.com|via\.placeholder\.com)(?=[\/:?#"\s]|$)/i;
const badBrand = /\b(?:recetagenial|recetadolce)\b/i;
const validSlug = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const str = value => typeof value === 'string' ? value.trim() : '';
const httpsUrl = value => {
  try { const u = new URL(value); return u.protocol === 'https:' && Boolean(u.hostname) && !u.username && !u.password && !reservedHost.test(value) && !['localhost', '127.0.0.1'].includes(u.hostname); }
  catch { return false; }
};
const distinct = items => [...new Set(items)];
function mediaOK(images) {
  return Array.isArray(images) && images.some(m => m && typeof m === 'object' && httpsUrl(m.url) && str(m.alt).length >= 10 && m.rights_verified === true && ['original', 'licensed'].includes(m.rights_type));
}
function stepOK(steps) { return Array.isArray(steps) && steps.length >= 3 && steps.every(s => str(s).length >= 15); }
function stitchRowsOK(rows) {
  return Array.isArray(rows) && rows.length > 0 && rows.every(r => {
    if (!r || typeof r !== 'object') return false;
    const fields = ['start', 'increases', 'decreases', 'end'].map(k => r[k]);
    return fields.every(x => Number.isSafeInteger(x) && x >= 0) && fields[0] > 0 && fields[0] + fields[1] - fields[2] === fields[3];
  });
}
export function auditPublication(post) {
  const issues = [];
  if (!post || typeof post !== 'object' || Array.isArray(post)) return ['NOT_AN_ARTICLE'];
  if (!KINDS.includes(post.kind)) issues.push('INVALID_KIND');
  if (!CATEGORIES.includes(post.category)) issues.push('INVALID_CATEGORY');
  if (!validSlug.test(str(post.slug))) issues.push('INVALID_SLUG');
  if (str(post.title).length < 15) issues.push('TITLE_TOO_SHORT');
  if (str(post.description).length < 65) issues.push('DESCRIPTION_TOO_SHORT');
  if (str(post.body).length < 600) issues.push('SUBSTANTIVE_BODY_REQUIRED');
  if (!['original', 'licensed'].includes(post.content_rights)) issues.push('RIGHTS_REQUIRED');
  if (!mediaOK(post.images)) issues.push('LICENSED_RELEVANT_IMAGE_REQUIRED');
  if (reservedHost.test(JSON.stringify(post)) || badBrand.test(JSON.stringify(post))) issues.push('PLACEHOLDER_OR_CROSSBRAND_DATA');
  if (['Recipe', 'HowTo', 'Product'].includes(post.schema_type)) issues.push('UNSUPPORTED_SCHEMA');
  if (post.kind === 'roundup') {
    if (!Array.isArray(post.source_links) || post.source_links.length < 2 || !post.source_links.every(httpsUrl)) issues.push('SOURCED_ROUNDUP_LINKS_REQUIRED');
  } else {
    if (!stepOK(post.steps)) issues.push('COMPLETE_STEPS_REQUIRED');
    if (!['US', 'UK'].includes(post.terminology)) issues.push('CROCHET_TERMINOLOGY_REQUIRED');
  }
  if (post.kind === 'pattern') {
    if (!Array.isArray(post.materials) || post.materials.length < 2 || !post.materials.every(v => str(v).length >= 3)) issues.push('MATERIALS_REQUIRED');
    for (const field of ['hook_size_mm', 'yarn_weight', 'gauge', 'finished_dimensions']) {
      if (!str(post[field])) issues.push(field.toUpperCase() + '_REQUIRED');
    }
    if (!stitchRowsOK(post.stitch_count_checks)) issues.push('STITCH_MATH_REQUIRED');
    const proof = post.test_evidence;
    if (!proof || proof.test_status !== 'physically_tested' || str(proof.tester_name).length < 3 || str(proof.test_notes).length < 40 || !httpsUrl(proof.prototype_photo_url) || proof.human_attested !== true) issues.push('INDEPENDENT_PHYSICAL_TEST_EVIDENCE_REQUIRED');
  }
  return distinct(issues);
}
const max = (v,n) => str(v).slice(0,n);
export function normalizeDraft(source) {
  if (!source || typeof source !== 'object' || Array.isArray(source)) throw new Error('INVALID_DRAFT');
  const rawImages = Array.isArray(source.images) ? source.images.slice(0,24) : [];
  const draft = {
    slug: max(source.slug,110).toLowerCase(),
    title: max(source.title,180),
    description: max(source.description,400),
    kind: KINDS.includes(source.kind) ? source.kind : 'tutorial',
    category: CATEGORIES.includes(source.category) ? source.category : 'beginners',
    body: max(source.body,180000),
    content_rights: ['original','licensed'].includes(source.content_rights) ? source.content_rights : 'unverified',
    terminology: ['US','UK'].includes(source.terminology) ? source.terminology : null,
    images: rawImages.map(img => ({url:max(img?.url,2000),alt:max(img?.alt,220),rights_verified:img?.rights_verified===true,rights_type:['original','licensed'].includes(img?.rights_type)?img.rights_type:'unverified'})),
    steps: (Array.isArray(source.steps)?source.steps:[]).slice(0,300).map(v=>max(v,4000)),
    materials: (Array.isArray(source.materials)?source.materials:[]).slice(0,120).map(v=>max(v,300)),
    source_links: (Array.isArray(source.source_links)?source.source_links:[]).slice(0,50).map(v=>max(v,2000)),
    hook_size_mm:max(source.hook_size_mm,60), yarn_weight:max(source.yarn_weight,100), gauge:max(source.gauge,300), finished_dimensions:max(source.finished_dimensions,300),
    stitch_count_checks: (Array.isArray(source.stitch_count_checks)?source.stitch_count_checks:[]).slice(0,600).map(r=>({start:r?.start,increases:r?.increases,decreases:r?.decreases,end:r?.end})),
    test_evidence: {
      test_status:source.test_evidence?.test_status === 'physically_tested' ? 'physically_tested' : 'untested',
      tester_name:max(source.test_evidence?.tester_name,160),test_notes:max(source.test_evidence?.test_notes,8000),
      prototype_photo_url:max(source.test_evidence?.prototype_photo_url,2000), human_attested:source.test_evidence?.human_attested === true,
    },
    seo_keyword:max(source.seo_keyword,180),
    research_evidence: source.research_evidence && typeof source.research_evidence==='object' && !Array.isArray(source.research_evidence) ? {market:max(source.research_evidence.market,100),source_type:max(source.research_evidence.source_type,100),source_url:max(source.research_evidence.source_url,1000),third_party_volume:Number.isSafeInteger(source.research_evidence.third_party_volume)&&source.research_evidence.third_party_volume>0?source.research_evidence.third_party_volume:null,verified_by_google:false,organic_difficulty:null}: {},
  };
  if (!validSlug.test(draft.slug)) throw new Error('INVALID_SLUG');
  if (draft.title.length < 6) throw new Error('TITLE_REQUIRED');
  if (reservedHost.test(JSON.stringify(draft)) || badBrand.test(JSON.stringify(draft))) throw new Error('PLACEHOLDER_OR_CROSSBRAND_DATA');
  return draft;
}
