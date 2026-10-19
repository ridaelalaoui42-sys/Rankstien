import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {learningGuides,guideCategories,guideBySlug,getRelatedGuides,guideWordCount} from '../lib/guides.mjs';
const root=resolve(import.meta.dirname,'..');
const file=rel=>readFileSync(join(root,rel));
const text=rel=>file(rel).toString('utf8');

test('twelve substantive independently written guide references with unique SEO targets',()=>{
  assert.equal(learningGuides.length,12);
  const slugs=new Set(),titles=new Set();
  for(const g of learningGuides){
    assert.match(g.slug,/^[a-z][a-z0-9-]{4,70}$/);assert(!slugs.has(g.slug));slugs.add(g.slug);
    assert(!titles.has(g.title));titles.add(g.title);
    assert(g.title.length>35&&g.title.length<90);
    assert(g.description.length>75&&g.description.length<175);
    assert(g.lead.length>100);
    assert(g.answer.length>100);
    assert(guideWordCount(g)>=450,`Too little original reference content: ${g.slug}`);
    assert(g.sections.length>=5,`Guide ${g.slug} needs depth`);
    assert(g.checklist.length>=4);
    assert(g.keywords.length>=2);
    assert(g.categoryId!=='all'&&guideCategories.some(c=>c.id===g.categoryId));
    assert.strictEqual(guideBySlug(g.slug),g);
  }
});

test('consistent internal linking with no missing, repeated or self references',()=>{
  for(const g of learningGuides){
    assert(g.related.length>=2);
    assert.equal(g.related.length,new Set(g.related).size);
    assert(!g.related.includes(g.slug));
    assert.equal(getRelatedGuides(g).length,g.related.length,`Broken related links: ${g.slug}`);
    assert.equal(g.sections.length,new Set(g.sections.map(s=>s.id)).size);
    for(const s of g.sections){
      assert.match(s.id,/^[a-z][a-z0-9-]+$/);assert(s.title.length>9);
      assert(Array.isArray(s.paragraphs)&&s.paragraphs.length>0);
      assert(s.paragraphs.some(p=>p.length>=80));
      assert(!s.paragraphs.some(p=>/https?:\/\//.test(p)),'URLs should be cited, not buried in copy');
    }
  }
});

test('all educational SVG assets have accessible labels and zero prohibited external dependencies',()=>{
  for(const g of learningGuides){
    assert.match(g.visual,/^\/guides\/[a-z0-9-]+\.svg$/);
    const asset='public'+g.visual;
    assert(existsSync(join(root,asset)),`${asset} not found`);
    const svg=text(asset);
    assert(svg.includes('<svg')&&svg.includes('role="img"')&&svg.includes('<title')&&svg.includes('<desc'));
    assert(!/<script|<foreignObject|https?:\/\//.test(svg.replace('http://www.w3.org/2000/svg','')));
    assert(svg.length<30000,'Keep educational vectors compact');
  }
});

test('all twelve Pinterest concept graphics are real 1000×1500 PNGs with no unapproved destinations',()=>{
  const pins=JSON.parse(text('docs/PINTEREST_ASSETS_MANIFEST.json'));
  assert.equal(pins.site,'Stitch Atlas');assert.equal(pins.destinationHost,null);assert.equal(pins.autopublish,false);
  assert.equal(pins.pins.length,learningGuides.length);
  const slugs=new Set(learningGuides.map(g=>g.slug));
  for(const pin of pins.pins){
    assert(slugs.has(pin.slug));assert.equal(pin.targetPath,'/guides/'+pin.slug);
    assert.equal(pin.image,'/pins/'+pin.slug+'.png');
    assert.equal(pin.approvedToPublish,false);
    assert.match(pin.status,/draft/);
    assert(!/example\.(?:com|net|org)|dummyimage|placehold/i.test(JSON.stringify(pin)));
    const pathname=join(root,'public'+pin.image);
    assert(statSync(pathname).size>20000);
    const bytes=file('public'+pin.image);
    assert.equal(bytes.subarray(0,8).toString('hex'),'89504e470d0a1a0a');
    assert.equal(bytes.readUInt32BE(16),1000);
    assert.equal(bytes.readUInt32BE(20),1500);
  }
});

test('all factual background links are real HTTPS sources, with no unverified review scores',()=>{
  for(const g of learningGuides){
    assert(g.sources.length>=1);
    for(const src of g.sources){
      const u=new URL(src.url);assert.equal(u.protocol,'https:');
      assert(!u.hostname.endsWith('example.com'));
      assert(src.title.length>9);
    }
    const blob=JSON.stringify(g);
    assert(!/aggregateRating|reviewCount|\"test_status\":\"physically_tested\"|fake review/i.test(blob));
    assert(!/\b(?:Buy now|instant download|PDF purchase)\b/i.test(blob));
  }
});

test('SEO preview remains noindex; Article schema cannot invent preview canonical URLs',()=>{
  assert(text('app/layout.jsx').includes('index:false,follow:false'));
  assert(text('app/robots.js').includes("disallow:'/'"));
  const guideRoute=text('app/guides/[slug]/page.jsx');
  assert(guideRoute.includes('STITCH_ATLAS_INDEXING_ENABLED'));
  assert(guideRoute.includes('canPublishSchema?'));
  assert(guideRoute.includes("'@type':'Article'"));
  assert(!guideRoute.includes("'@type':'Recipe'"));
  assert(!guideRoute.includes("'@type':'HowTo'"));
  assert(!guideRoute.includes('datePublished'));
  assert(guideRoute.includes('generateStaticParams'));
  assert(guideRoute.includes('notFound()'));
});

test('connected reading architecture includes home, pattern hubs, header and footer',()=>{
  const home=text('app/page.jsx'),pattern=text('app/patterns/page.jsx');
  assert(home.includes('<GuideCollection'));
  assert(pattern.includes('<GuideCollection'));
  assert(text('components/SiteHeader.jsx').includes("['/guides','Free guides']"));
  assert(text('components/Footer.jsx').includes('href="/guides"'));
  assert(text('app/guides/page.jsx').includes('<GuideCatalog'));
  assert(existsSync(join(root,'styles/guides.css')));
});
