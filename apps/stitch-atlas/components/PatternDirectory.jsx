'use client';
import {useEffect,useMemo,useState} from 'react';
import Image from 'next/image';
import Link from 'next/link';
import {topics,categories} from '../lib/topics';
export default function PatternDirectory({compact=false}){
 const [search,setSearch]=useState('');const[category,setCategory]=useState('all');
 useEffect(()=>{const selected=new URLSearchParams(window.location.search).get('category');if(selected&&categories.some(c=>c.id===selected))setCategory(selected)},[]);
 const filtered=useMemo(()=>topics.filter(t=>(category==='all'||t.group===category)&&[t.title,t.description,t.tag,t.kind].join(' ').toLowerCase().includes(search.trim().toLowerCase())),[search,category]);
 return <div className="directory"><div className="directory-toolbar"><div className="filter-chips" role="group" aria-label="Filter topic collection"><button type="button" className={category==='all'?'selected':''} aria-pressed={category==='all'} onClick={()=>setCategory('all')}>All studies</button>{categories.map(t=><button type="button" key={t.id} aria-pressed={category===t.id} className={category===t.id?'selected':''} onClick={()=>setCategory(t.id)}>{t.label}</button>)}</div><div className="directory-search"><label htmlFor="search-topics">Search topics</label><div><span aria-hidden="true">⌕</span><input type="search" id="search-topics" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Try ‘bag’, ‘moss’ or ‘yarn’" autoComplete="off"/></div></div></div><div className="cards-grid" aria-live="polite">
 {filtered.slice(0,compact?6:topics.length).map((t,i)=><article className="topic-card" key={t.slug}><div className={'topic-art '+t.color}><span className="topic-numeral">STUDY / {String(i+1).padStart(2,'0')}</span><Image src={t.image} width={230} height={230} alt="" loading="lazy"/><span className="topic-art-badge">IN DEVELOPMENT</span></div><div className="topic-content"><div className="topic-meta"><span>{t.tag}</span><span>✳ {t.level}</span></div><h3>{t.title}</h3><p>{t.description}</p><div className="topic-bottom"><span>{t.kind}</span><span className="arrow" aria-hidden="true">↗</span></div></div></article>)}
 </div>{!filtered.length?<p className="empty-search">No topics match this search. Try another stitch or category.</p>:null}<div className="directory-bottom"><span>{filtered.length} research-stage {filtered.length===1?'topic':'topics'}</span>{compact?<Link href="/patterns">View the full editorial queue ↗</Link>:<span>Original patterns are not published until independently tested.</span>}</div></div>
}
