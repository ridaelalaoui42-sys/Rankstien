'use client';
import {useMemo,useState} from 'react';
import GuideCollection from './GuideCollection';
import {guideCategories,learningGuides} from '../lib/guides.mjs';

export default function GuideCatalog(){
  const [term,setTerm]=useState(''),[category,setCategory]=useState('all');
  const guides=useMemo(()=>learningGuides.filter(guide=>{
    if(category!=='all'&&guide.categoryId!==category)return false;
    const haystack=[guide.title,guide.description,guide.category,...guide.keywords].join(' ').toLowerCase();
    return haystack.includes(term.trim().toLowerCase());
  }),[term,category]);
  return <div className="guides-catalog">
    <div className="guides-controls">
      <div className="guides-filter-list" role="group" aria-label="Filter learning guides">
        {guideCategories.map(c=><button type="button" key={c.id} aria-pressed={category===c.id} className={category===c.id?'is-selected':''} onClick={()=>setCategory(c.id)}>{c.label}</button>)}
      </div>
      <label className="guides-search-label">Find a guide<input type="search" placeholder="Try gauge, straps, stitch count…" value={term} onChange={e=>setTerm(e.target.value)}/></label>
    </div>
    <p className="guides-results" role="status" aria-live="polite">{guides.length} {guides.length===1?'guide':'guides'} in this collection</p>
    {guides.length?<GuideCollection guides={guides}/>:<div className="guides-empty"><h2>No guide matches that search.</h2><p>Try a different stitch, project type or broader term.</p><button type="button" onClick={()=>{setTerm('');setCategory('all')}}>Show every guide</button></div>}
  </div>
}
