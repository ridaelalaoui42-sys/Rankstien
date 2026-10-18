/** Local-only editorial queue. No Supabase/production publication or remote side effects. */
import {auditPublication,normalizeDraft} from './editorial-contract.mjs';

export const WORKSPACE_FORMAT='stitch-atlas-offline-workspace-v1';
export const HANDOFF_FORMAT='stitch-atlas-editorial-handoff-v1';
export const STORAGE_KEY='stitch-atlas:offline-drafts:v1';
export const MAX_DRAFTS=60;
export const MAX_IMPORT_BYTES=3_500_000;

export function blankDraft() {
  return {slug:'',title:'',description:'',kind:'tutorial',category:'beginners',body:'',content_rights:'unverified',terminology:'US',images:[],steps:[],materials:[],source_links:[],hook_size_mm:'',yarn_weight:'',gauge:'',finished_dimensions:'',stitch_count_checks:[],test_evidence:{test_status:'untested',human_attested:false},seo_keyword:'',research_evidence:{}};
}
export function slugFromTitle(title) {
  return String(title||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,110).replace(/-$/,'');
}
export function normalizeOfflineItem(input, id, savedAt=new Date().toISOString()) {
  const candidate={...blankDraft(),...input};
  // Immutable local queue properties and roles can NEVER come from an import.
  const article=normalizeDraft(candidate);
  // Browser-only records must never carry alleged physical testing proof into
  // a future authenticated CMS; real makers/reviewers must attest there.
  article.test_evidence={test_status:'untested',tester_name:'',test_notes:'',prototype_photo_url:'',human_attested:false};
  return {id:String(id),...article,status:'draft',saved_at:savedAt};
}
export function workItemIssues(item) { return auditPublication(item); }
export function summarizeWorkspace(items) {
  return {total:items.length, structurally_complete:items.filter(x=>workItemIssues(x).length===0).length,
    needs_work:items.filter(x=>workItemIssues(x).length>0).length, published:0};
}
export function exportWorkspace(items) {
  if (!Array.isArray(items)||items.length>MAX_DRAFTS) throw Error('WORKSPACE_TOO_LARGE');
  return {format_version:WORKSPACE_FORMAT,vertical:'crochet',publication_enabled:false,
    exported_at:new Date().toISOString(),disclaimer:'Unpublished drafts stored in the editor browser; not verified as physically tested or approved.',
    drafts:items.map((item,index)=>normalizeOfflineItem(item,item.id||`draft-${index}`,item.saved_at))};
}
function ensureSafeRoot(data) {
  if(!data||typeof data!=='object'||Array.isArray(data)||data.vertical!=='crochet')throw Error('NOT_A_CROCHET_WORKSPACE');
  if(data.publication_enabled!==false || data.publishing_enabled===true)throw Error('PUBLICATION_MUST_REMAIN_DISABLED');
}
function parseWorkspaceImport(data) {
  ensureSafeRoot(data);
  let originals=[];
  if(data.format_version===WORKSPACE_FORMAT&&Array.isArray(data.drafts)) originals=data.drafts;
  else if(data.format_version===HANDOFF_FORMAT&&Array.isArray(data.proposals)) originals=data.proposals;
  else throw Error('UNSUPPORTED_RESEARCH_FORMAT');
  if(originals.length>MAX_DRAFTS)throw Error('WORKSPACE_LIMIT_60_DRAFTS');
  const seen=new Set(),drafts=[];let skipped=0;
  for(const entry of originals){
    try{
      if(!entry||typeof entry!=='object'||Array.isArray(entry))throw Error('INVALID_ENTRY');
      const slug=entry.slug||slugFromTitle(entry.title);
      if(seen.has(slug)){skipped++;continue;}
      const normalized=normalizeOfflineItem({...entry,slug},slug);
      // Research handoffs are never allowed to assert licensed content, reviews, or original work.
      if(data.format_version===HANDOFF_FORMAT){
        normalized.content_rights='unverified';
        normalized.test_evidence={test_status:'untested',tester_name:'',test_notes:'',prototype_photo_url:'',human_attested:false};
        normalized.images=[];normalized.steps=[];normalized.body='';
        normalized.status='draft';
      }
      seen.add(slug);drafts.push(normalized);
    }catch{skipped++;}
  }
  return {drafts,skipped};
}
export function parseWorkspaceText(raw) {
  if(typeof raw!=='string'||new TextEncoder().encode(raw).length>MAX_IMPORT_BYTES)throw Error('IMPORT_FILE_TOO_LARGE');
  let data;try{data=JSON.parse(raw)}catch{throw Error('INVALID_JSON_FILE')}
  return parseWorkspaceImport(data);
}
export function mergeWorkspaces(current,incoming){
  const known=new Set(current.map(x=>x.slug));const items=[...current];let added=0,skipped=0;
  for(const d of incoming){
    if(items.length>=MAX_DRAFTS||known.has(d.slug)){skipped++;continue;}
    const article=normalizeOfflineItem(d,d.id||d.slug);items.push(article);known.add(article.slug);added++;
  }
  return {items,added,skipped};
}
export function loadLocalWorkspace(storage) {
  if(!storage) return {items:[],error:null};
  try{
    const data=storage.getItem(STORAGE_KEY);
    if(!data)return {items:[],error:null};
    const parsed=parseWorkspaceText(data);
    if(parsed.skipped) return {items:[],error:`${parsed.skipped} invalid local entries detected. Existing browser storage is preserved. Export/recover it manually before editing.`};
    return {items:parsed.drafts,error:null};
  }catch{return {items:[],error:'Saved workspace could not be loaded. Existing storage was not changed; please recover it before editing.'}}
}
export function saveLocalWorkspace(storage,items) {
  if(!storage)throw Error('LOCAL_STORAGE_UNAVAILABLE');
  storage.setItem(STORAGE_KEY,JSON.stringify(exportWorkspace(items)));
  return items.length;
}
