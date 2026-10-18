import {notFound} from 'next/navigation';
import Link from 'next/link';
import {publishedCraftArticle} from '../../../lib/public-craft.mjs';
const escapeScript=value=>JSON.stringify(value).replace(/</g,'\\u003c').replace(/\u2028|\u2029/g,'');
export async function generateMetadata({params}){
  const {slug}=await params;const article=await publishedCraftArticle(slug);
  if(!article)return{title:'Pattern not available',robots:{index:false}};
  return{title:article.title,description:article.description,openGraph:{type:'article',title:article.title,description:article.description}};
}
export default async function PatternArticle({params}){
  const {slug}=await params;const article=await publishedCraftArticle(slug);if(!article)notFound();
  const image=article.images?.find(x=>x?.rights_verified&&x.url?.startsWith('https://')&&x.alt);
  const siteUrl=process.env.NEXT_PUBLIC_SITE_URL;
  const jsonld={ '@context':'https://schema.org','@type':article.kind==='pattern'?'CreativeWork':'Article',name:article.title,description:article.description,datePublished:article.published_at,inLanguage:'en',isAccessibleForFree:true,url:siteUrl?.startsWith('https://')?siteUrl+'/patterns/'+article.slug:undefined,image:image?.url, publisher:{'@type':'Organization',name:'Stitch Atlas'} };
  return <main id="main"><div className="inner-hero"><div className="container"><p className="kicker">THE STITCH ATLAS LIBRARY / {article.kind.replaceAll('_',' ').toUpperCase()}</p><h1>{article.title}</h1><p>{article.description}</p><Link className="text-link" href="/patterns">← Return to library</Link></div></div><div className="container article-layout public-article-layout"><aside className="article-toc"><h2>IN THIS GUIDE</h2><a href="#overview">Overview</a>{article.materials?.length?<a href="#materials">Materials</a>:null}{article.steps?.length?<a href="#steps">The steps</a>:null}<Link href="/tools">Maker tools ↗</Link></aside><article className="prose" id="overview">
    {image?<figure className="article-cover"><img src={image.url} alt={image.alt} width="1080" height="720" loading="eager" fetchPriority="high"/><figcaption>Original or licensed editorial imagery.</figcaption></figure>:null}
    {article.body.split(/\n\n+/).map((p,i)=><p key={i}>{p}</p>)}
    {article.materials?.length?<section id="materials"><h2>Materials</h2><ul>{article.materials.map((m,i)=><li key={i}>{m}</li>)}</ul>{article.gauge?<p>Gauge: {article.gauge}</p>:null}{article.finished_dimensions?<p>Finished measurements: {article.finished_dimensions}</p>:null}</section>:null}
    {article.steps?.length?<section id="steps"><h2>Step by step</h2><ol>{article.steps.map((s,i)=><li key={i}>{s}</li>)}</ol></section>:null}
    {article.kind==='pattern'?<div className="article-note"><b>INDIVIDUALLY REVIEWED PATTERN</b><p>This pattern passed the editorial review and physical-test evidence checks before publication. Check your gauge before starting; yarn and personal tension can affect finished measurements.</p></div>:null}
    <script type="application/ld+json" dangerouslySetInnerHTML={{__html:escapeScript(jsonld)}}/>
  </article></div></main>;
}
