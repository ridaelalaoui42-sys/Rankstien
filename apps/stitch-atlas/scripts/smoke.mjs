import assert from 'node:assert/strict';
const root=(process.env.STITCH_ATLAS_BASE_URL||'http://127.0.0.1:3000').replace(/\/$/,'');
for(const [path,expected] of [['/','There’s beauty in'],['/patterns','Patterns for a'],['/learn','Every maker starts'],['/tools','Small helpers'],['/about','Craft deserves']]){
 const r=await fetch(root+path);assert.equal(r.status,200,`${path} status ${r.status}`);const html=await r.text();assert(html.includes(expected),`${path} missing headline`);
 assert(/noindex/.test(html),`${path} preview MUST remain non-indexable`);
}
for(const path of ['/brand/mark.svg','/brand/wordmark.svg','/brand/wordmark-inverse.svg','/images/editorial-hero.jpg','/category/bag.svg','/category/yarn.svg','/brand/social-cover.jpg','/brand/pinterest-concept.jpg']){
 const r=await fetch(root+path);assert.equal(r.status,200,`${path} HTTP status`);assert(Number(r.headers.get('content-length')||'1')>0,`${path} empty asset`);
}
const robots=await (await fetch(root+'/robots.txt')).text();assert(robots.includes('Disallow: /'),'Preview robots must disallow crawling');
console.log('Stitch Atlas HTTP / SEO / brand-asset smoke checks passed.');
