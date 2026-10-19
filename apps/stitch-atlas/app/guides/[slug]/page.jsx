import Image from 'next/image';
import Link from 'next/link';
import {notFound} from 'next/navigation';
import GuideCollection from '../../../components/GuideCollection';
import GuideActions from '../../../components/GuideActions';
import {guideBySlug,getRelatedGuides,learningGuides,guideWordCount} from '../../../lib/guides.mjs';

export const dynamicParams=false;
export function generateStaticParams(){return learningGuides.map(g=>({slug:g.slug}))}
export async function generateMetadata({params}){
  const {slug}=await params,guide=guideBySlug(slug);
  if(!guide)return {title:'Guide not found',robots:{index:false}};
  return {title:guide.title,description:guide.description,openGraph:{title:guide.title,description:guide.description,images:[{url:'/og-cover.jpg',width:900,height:600,alt:'Stitch Atlas — independent crochet learning'}]}};
}
function RenderSection({section}){
  return <section className="guide-body-section" id={section.id} aria-labelledby={'heading-'+section.id}>
    <h2 id={'heading-'+section.id}>{section.title}</h2>
    {section.paragraphs?.map((p,i)=><p key={i}>{p}</p>)}
    {section.bullets?<ul>{section.bullets.map((x,i)=><li key={i}>{x}</li>)}</ul>:null}
    {section.steps?<ol className="guide-numbered-list">{section.steps.map((x,i)=><li key={i}>{x}</li>)}</ol>:null}
    {section.table?<div className="guide-table-wrap" tabIndex={0} role="region" aria-label="US to UK crochet stitch conversion reference"><table><caption>Stitch equivalence for common US and UK terminology</caption><thead><tr>{section.table.head.map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{section.table.rows.map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j}>{v}</td>)}</tr>)}</tbody></table></div>:null}
    {section.note?<aside className="guide-note" aria-label="Field note"><span>FIELD NOTE / ✳</span><h3>{section.note.heading}</h3><p>{section.note.body}</p></aside>:null}
  </section>
}
export default async function GuidePage({params}){
  const {slug}=await params,guide=guideBySlug(slug);
  if(!guide)notFound();
  const related=getRelatedGuides(guide),readMinutes=Math.max(3,Math.ceil(guideWordCount(guide)/210));
  // Preview does not emit misleading production URLs or pretend indexing is enabled.
  const canPublishSchema=process.env.STITCH_ATLAS_INDEXING_ENABLED==='true'&&/^https:\/\//.test(process.env.NEXT_PUBLIC_SITE_URL||'');
  const schema=canPublishSchema?{'@context':'https://schema.org','@type':'Article',headline:guide.title,description:guide.description,image:new URL(guide.visual,process.env.NEXT_PUBLIC_SITE_URL).href,mainEntityOfPage:new URL('/guides/'+guide.slug,process.env.NEXT_PUBLIC_SITE_URL).href,isAccessibleForFree:true,publisher:{'@type':'Organization',name:'Stitch Atlas'}}:null;
  return <main id="main" className="guide-page">
    {schema?<script type="application/ld+json" dangerouslySetInnerHTML={{__html:JSON.stringify(schema).replace(/</g,'\\u003c')}}/>:null}
    <div className="container guide-breadcrumb"><Link href="/">Home</Link><span aria-hidden="true">/</span><Link href="/guides">Learning guides</Link><span aria-hidden="true">/</span><span aria-current="page">{guide.shortTitle}</span></div>
    <header className="guide-header"><div className="container guide-header-inner"><div className="guide-header-copy"><p className="kicker">THE MAKER’S NOTEBOOK / {guide.category.toUpperCase()}</p><h1>{guide.title}</h1><p className="guide-lede">{guide.lead}</p><div className="guide-meta"><span>FREE LEARNING REFERENCE</span><span aria-hidden="true">✳</span><span>ABOUT {readMinutes} MIN READ</span></div><GuideActions slug={slug}/><Link href="/academy" className="academy-lesson-guide-cta">Learn through illustrated quizzes →</Link></div><figure className={'guide-hero-figure guide-hero-'+guide.accent}><Image src={guide.visual} width={1200} height={720} alt={guide.shortTitle+' — an original illustrated explanation'} priority sizes="(max-width: 900px) 92vw, 48vw"/><figcaption>Original Stitch Atlas schematic · Educational illustration, not a tested pattern.</figcaption></figure></div></header>
    <div className="container guide-article-shell"><aside className="guide-sticky-index" aria-label="On this page"><h2>INSIDE THIS GUIDE</h2><nav aria-label="Guide sections">{guide.sections.map(section=><a key={section.id} href={'#'+section.id}>{section.title.replace(/^\d+\.\s*/, '')}</a>)}</nav><div className="guide-index-tools"><span>✳ TAKE YOUR TIME</span><Link href="/tools">Open the Maker Desk ↗</Link></div></aside>
    <article className="guide-article">
      <div className="guide-answer"><span>THE SHORT ANSWER</span><p>{guide.answer}</p></div>
      <section className="guide-checklist" aria-labelledby="guide-checklist-title"><h2 id="guide-checklist-title">Before you begin</h2><ul>{guide.checklist.map((item,i)=><li key={i}><span aria-hidden="true">✓</span>{item}</li>)}</ul></section>
      {guide.sections.map(section=><RenderSection section={section} key={section.id}/>)}
      <section className="guide-references" aria-labelledby="guide-sources-title"><h2 id="guide-sources-title">Sources &amp; further reading</h2><p>These external craft references support the general terms and techniques discussed here; this guide is independently written.</p><ul>{guide.sources.map(source=><li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title} <span aria-hidden="true">↗</span></a></li>)}</ul></section>
      <aside className="guide-editorial-note"><span>OUR EDITORIAL STANDARD</span><p>Technique explanation does not equal a physically tested project. Stitch Atlas never labels a new crochet pattern “tested” without real making and review evidence. This page is a learning reference, not a complete original pattern.</p></aside>
    </article></div>
    <section className="guide-related"><div className="container"><div className="guide-section-heading"><div><p className="kicker">KEEP FOLLOWING THE THREAD</p><h2>What to read <em>next.</em></h2></div><Link className="guide-section-link" href="/guides">Explore every learning guide ↗</Link></div><GuideCollection guides={related}/></div></section>
  </main>
}
