'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import {
  STORAGE_KEY,MAX_DRAFTS,MAX_IMPORT_BYTES,blankDraft,slugFromTitle,
  workItemIssues,summarizeWorkspace,normalizeOfflineItem,
  parseWorkspaceText,mergeWorkspaces,loadLocalWorkspace,saveLocalWorkspace,exportWorkspace,
} from '../lib/offline-workspace.mjs';

const categoryNames={bags:'Bags & totes',stitches:'Stitches',beginners:'Beginners',home:'Blankets & home',accessories:'Accessories',amigurumi:'Amigurumi',seasonal:'Seasonal'};
const kindNames={pattern:'Original pattern',tutorial:'Tutorial',stitch_guide:'Stitch guide',roundup:'Curated roundup'};
const asLines=value=>Array.isArray(value)?value.join('\n'):'';
const parseLines=text=>text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
const jsonEditor=(value,fallback='[]')=>JSON.stringify(value??JSON.parse(fallback),null,2);
const saveFile=(name,body)=>{const url=URL.createObjectURL(new Blob([body],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),500);};
function safeArrayJson(text,label){let value;try{value=JSON.parse(text||'[]')}catch{throw Error(`${label} contains invalid JSON`)}if(!Array.isArray(value))throw Error(`${label} must be a JSON array`);return value;}
function emptyForm(){return {...blankDraft(),slug:'',title:''};}

export default function OfflineDraftStudio(){
  const [loaded,setLoaded]=useState(false),[items,setItems]=useState([]),[active,setActive]=useState(''),
    [form,setForm]=useState(emptyForm),[steps,setSteps]=useState(''),[materials,setMaterials]=useState(''),
    [links,setLinks]=useState(''),[images,setImages]=useState('[]'),[rows,setRows]=useState('[]'),
    [status,setStatus]=useState(''),[storageError,setStorageError]=useState(false),[busy,setBusy]=useState(false),[filter,setFilter]=useState(''),
    [preview,setPreview]=useState(false),[dirty,setDirty]=useState(false);
  const upload=useRef(null);
  useEffect(()=>{
    const data=loadLocalWorkspace(window.localStorage);
    setItems(data.items);setStatus(data.error||'');setStorageError(Boolean(data.error));setLoaded(true);
  },[]);
  useEffect(()=>{const fn=e=>{if(dirty){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',fn);return()=>window.removeEventListener('beforeunload',fn)},[dirty]);
  const totals=useMemo(()=>summarizeWorkspace(items),[items]);
  const list=useMemo(()=>items.filter(x=>`${x.title} ${x.slug} ${x.seo_keyword}`.toLowerCase().includes(filter.toLowerCase())),[items,filter]);
  const field=(name,value)=>{setForm(prev=>({...prev,[name]:value}));setDirty(true);};
  const setText=(fn,value)=>{fn(value);setDirty(true)};
  const select=item=>{
    if(dirty&&!window.confirm('Discard unsaved changes to this draft?'))return;
    setActive(item.id);setForm(item);setSteps(asLines(item.steps));setMaterials(asLines(item.materials));
    setLinks(asLines(item.source_links));setImages(jsonEditor(item.images));setRows(jsonEditor(item.stitch_count_checks));
    setPreview(false);setDirty(false);setStatus('');
  };
  const create=()=>{
    if(dirty&&!window.confirm('Discard unsaved changes to this draft?'))return;
    setActive('');setForm(emptyForm());setSteps('');setMaterials('');setLinks('');setImages('[]');setRows('[]');setPreview(false);setDirty(false);setStatus('Start a new local draft, then click Save draft.');
  };
  const assemble=()=>({...form,steps:parseLines(steps),materials:parseLines(materials),source_links:parseLines(links),images:safeArrayJson(images,'Image metadata'),stitch_count_checks:safeArrayJson(rows,'Stitch math')});
  const blockers=useMemo(()=>{try{return workItemIssues(assemble())}catch(e){return [e.message]}},[form,steps,materials,links,images,rows]);
  const persist=next=>{if(storageError)throw Error('Existing saved workspace needs manual recovery before it can be overwritten.');saveLocalWorkspace(window.localStorage,next);setItems(next)};
  const save=()=>{
    try{
      if(!loaded)return;
      if(items.length>=MAX_DRAFTS&&!active)throw Error(`The local workspace limit is ${MAX_DRAFTS} drafts. Export your data before creating more.`);
      const id=active||crypto.randomUUID();
      const draft=normalizeOfflineItem(assemble(),id);
      const next=active?items.map(x=>x.id===active?draft:x):[draft,...items];
      persist(next);setActive(id);setForm(draft);setDirty(false);setStatus('Draft saved in this browser only. It is NOT submitted, approved or published.');
    }catch(e){setStatus(`Unable to save: ${e.message}. Export saved drafts regularly.`)}
  };
  const importFile=async event=>{
    const file=event.target.files?.[0];if(!file)return;
    if(dirty&&!window.confirm('Importing will leave your current unsaved edits untouched. Continue?')){if(upload.current)upload.current.value='';return;}
    setBusy(true);
    try{
      if(file.size>MAX_IMPORT_BYTES)throw Error('File is too large (3.5 MB max)');
      const {drafts,skipped}=parseWorkspaceText(await file.text());
      const {items:next,added,skipped:duplicate}=mergeWorkspaces(items,drafts);
      persist(next);setDirty(false);setStatus(`${added} unpublished drafts imported. ${skipped+duplicate} duplicate/invalid entries skipped. All require original writing and review.`);
    }catch(e){setStatus(`Import rejected: ${e.message}`)}finally{setBusy(false);if(upload.current)upload.current.value=''}
  };
  const exportFile=()=>{try{saveFile('stitch-atlas-unpublished-drafts.json',JSON.stringify(exportWorkspace(items),null,2));setStatus(`Exported ${items.length} local drafts. No publishing or upload occurred.`)}catch(e){setStatus('Export failed: '+e.message)}};
  const remove=()=>{
    if(!active)return;
    if(!window.confirm('Delete this draft from this browser? Export first if you need a backup.'))return;
    try{persist(items.filter(x=>x.id!==active));setActive('');setForm(emptyForm());setDirty(false);setPreview(false);setStatus('Local draft deleted; no live site content was changed.')}catch(e){setStatus('Delete failed: '+e.message)}
  };
  if(!loaded)return <div className="offline-loading" role="status">Preparing your local editorial workspace…</div>;
  return <div className="offline-workspace" data-testid="offline-studio">
    <div className="offline-heading"><div><p className="kicker">STITCH ATLAS · EDITORIAL DESK / SANDBOX</p><h1>Make room for <em>good ideas.</em></h1><p>Develop original crochet stories before the database is ready. Everything stays in this browser until you choose to export it.</p></div><div className="offline-mode-label" aria-label="Local draft mode, publication disabled"><span>● LOCAL ONLY</span><strong>Publishing is locked</strong></div></div>
    <div className="offline-metrics" aria-label="Draft workspace totals"><div><span>DRAFTS</span><strong>{totals.total}</strong></div><div><span>STRUCTURALLY COMPLETE*</span><strong>{totals.structurally_complete}</strong></div><div><span>NEEDS MORE WORK</span><strong>{totals.needs_work}</strong></div><div><span>LIVE PATTERNS</span><strong>0</strong></div></div>
    <p className="offline-metric-note">*Structural checks do not verify physical crochet testing, image licenses or human editorial approval.</p>
    <div className="offline-actions"><button type="button" onClick={create} className="btn-primary">+ New draft</button><label className="offline-file-label">Import Rankstien handoff / backup <input ref={upload} type="file" accept="application/json,.json" onChange={importFile} disabled={busy||storageError}/></label><button type="button" onClick={exportFile} className="offline-outline">Export draft backup ↗</button></div>
    <div className="offline-layout"><aside className="offline-sidebar"><div className="offline-sidebar-title"><h2>The draft queue</h2><span>{items.length}/{MAX_DRAFTS}</span></div><label className="offline-search">Find a draft<input type="search" placeholder="Search title or keyword" value={filter} onChange={e=>setFilter(e.target.value)}/></label>
      {list.length?<div className="offline-draft-list">{list.map(d=><button key={d.id} type="button" aria-pressed={active===d.id} onClick={()=>select(d)} className={active===d.id?'active':''}><span>LOCAL DRAFT · {kindNames[d.kind]||'Article'}</span><strong>{d.title}</strong><small>{d.seo_keyword||'No target keyword yet'}</small></button>)}</div>:<p className="offline-empty">No saved drafts here yet. Import a Rankstien research handoff or start writing your first original guide.</p>}
      <div className="offline-privacy"><strong>Privacy note</strong><p>Browser storage is convenient but not encrypted. Avoid confidential information, and export backups regularly. Other people using this browser profile may see these drafts.</p></div>
    </aside><section className="offline-editor" aria-labelledby="offline-form-title"><div className="offline-editor-header"><p className="kicker">{active?'EDITING A SAVED LOCAL DRAFT':'NEW EDITORIAL DRAFT'}</p><h2 id="offline-form-title">{active?'The work in progress':'The next chapter'}</h2><p>No draft can become publicly accessible from this workspace.</p></div>
      <div className="offline-tabs" role="group" aria-label="Workspace view"><button type="button" className={!preview?'chosen':''} aria-pressed={!preview} onClick={()=>setPreview(false)}>Write & verify</button><button type="button" className={preview?'chosen':''} aria-pressed={preview} onClick={()=>setPreview(true)}>Private reading preview</button></div>
      {preview?<div className="offline-preview" aria-label="Unpublished article reading preview"><p className="kicker">UNPUBLISHED DRAFT / LOCAL PREVIEW</p><h2>{form.title||'Your future story'}</h2><p className="offline-preview-summary">{form.description||'A useful short introduction will appear here.'}</p>{String(form.body||'').split(/\n\s*\n/).filter(Boolean).map((p,i)=><p key={i}>{p}</p>)}{parseLines(steps).length?<section><h3>Working notes and steps</h3><ol>{parseLines(steps).map((p,i)=><li key={i}>{p}</li>)}</ol></section>:null}<p className="offline-preview-foot">This is a private text preview. It does not imply physical pattern testing or editorial approval.</p></div>
      :<div className="offline-form">
        <div className="offline-pair"><label>Story format<select value={form.kind} onChange={e=>field('kind',e.target.value)}>{Object.entries(kindNames).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label><label>Editorial collection<select value={form.category} onChange={e=>field('category',e.target.value)}>{Object.entries(categoryNames).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label></div>
        <label>Working headline<input value={form.title||''} maxLength={180} onChange={e=>{const value=e.target.value;setForm(prev=>({...prev,title:value,slug:(!active&&(!prev.slug||prev.slug===slugFromTitle(prev.title)))?slugFromTitle(value):prev.slug}));setDirty(true)}} placeholder="How to count crochet stitches in the round"/></label>
        <label>URL slug<input value={form.slug||''} maxLength={110} onChange={e=>field('slug',e.target.value.toLowerCase())} placeholder="how-to-count-crochet-stitches"/></label>
        <label>Primary SEO keyword<input value={form.seo_keyword||''} maxLength={180} onChange={e=>field('seo_keyword',e.target.value)} placeholder="crochet stitches for beginners"/></label>
        <label>Editorial summary<textarea rows={3} value={form.description||''} onChange={e=>field('description',e.target.value)} placeholder="Explain the exact problem your article will solve."/></label>
        <label>Original article text<textarea rows={11} value={form.body||''} onChange={e=>field('body',e.target.value)} placeholder="Write original, fact-checked instructions. Separate paragraphs with a blank line."/></label>
        <div className="offline-pair"><label>Image / text permissions<select value={form.content_rights||'unverified'} onChange={e=>field('content_rights',e.target.value)}><option value="unverified">Unverified — cannot publish</option><option value="original">Original work</option><option value="licensed">Licensed work</option></select></label><label>Terminology<select value={form.terminology||'US'} onChange={e=>field('terminology',e.target.value)}><option value="US">US crochet terms</option><option value="UK">UK crochet terms</option></select></label></div>
        <label>Instructions or reference steps (one per line)<textarea rows={5} value={steps} onChange={e=>setText(setSteps,e.target.value)}/></label>
        <details><summary>Material notes, references and media rights</summary><label>Materials (one per line)<textarea rows={3} value={materials} onChange={e=>setText(setMaterials,e.target.value)}/></label><label>Referenced original sources (one URL per line)<textarea rows={3} value={links} onChange={e=>setText(setLinks,e.target.value)}/></label><label>Image evidence JSON (URLs, alt text, real rights verification)<textarea rows={6} value={images} onChange={e=>setText(setImages,e.target.value)}/></label></details>
        {form.kind==='pattern'?<details open><summary>Pattern testing — real-world evidence required</summary><div className="offline-pair"><label>Hook size (mm)<input value={form.hook_size_mm||''} onChange={e=>field('hook_size_mm',e.target.value)}/></label><label>Yarn weight<input value={form.yarn_weight||''} onChange={e=>field('yarn_weight',e.target.value)}/></label></div><label>Gauge<input value={form.gauge||''} onChange={e=>field('gauge',e.target.value)}/></label><label>Finished dimensions<input value={form.finished_dimensions||''} onChange={e=>field('finished_dimensions',e.target.value)}/></label><label>Stitch-count JSON rows<textarea rows={5} value={rows} onChange={e=>setText(setRows,e.target.value)}/></label><p>Do not mark a pattern as tested here. The future authenticated CMS will require a genuine independent crocheter, test notes and photographs.</p></details>:null}
        <div className="offline-quality"><div><h3>Publication-readiness checklist</h3><span>{blockers.length?`${blockers.length} open checks`:'No automated structural blockers'}</span></div>{blockers.length?<ul>{blockers.slice(0,14).map(x=><li key={x}>{x.replaceAll('_',' ').toLowerCase()}</li>)}</ul>:<p>Structure looks complete. Independent craft testing and a real editor are still required; publishing remains locked.</p>}</div>
      </div>}
      <div className="offline-footer-actions"><button type="button" className="btn-primary" onClick={save} disabled={busy||storageError}>Save local draft</button>{active?<button type="button" className="offline-danger" onClick={remove} disabled={storageError}>Delete local draft</button>:null}<span>{dirty?'● Unsaved changes':'No unsaved edits'}</span></div>
      {status?<p role="status" className="offline-notice">{status}</p>:null}
    </section></div>
  </div>;
}
