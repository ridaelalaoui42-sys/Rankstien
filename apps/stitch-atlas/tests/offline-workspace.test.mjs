import test from 'node:test';
import assert from 'node:assert/strict';
import {
  WORKSPACE_FORMAT,HANDOFF_FORMAT,STORAGE_KEY,MAX_DRAFTS,blankDraft,slugFromTitle,
  normalizeOfflineItem,summarizeWorkspace,exportWorkspace,parseWorkspaceText,
  mergeWorkspaces,saveLocalWorkspace,loadLocalWorkspace,
} from '../lib/offline-workspace.mjs';

const text='Original crochet guide discussing the different ways to count rows, recognize turning chains and fix uneven edges safely. ';
function input(){return {...blankDraft(),title:'Crochet row counting made simple',slug:'crochet-row-counting',body:text.repeat(7),description:'Beginner-friendly advice on counting rows, finding turning chains, and preserving accurate stitch totals.',steps:['Look at the top loops of each stitch and find your previous starting point.','Count the stitches in the current row, ignoring any turning chain not counted by the pattern.','Compare with a measurement sample and double-check your count before continuing.'],kind:'tutorial',category:'beginners',content_rights:'original',images:[{url:'https://studio.test/original-work.webp',alt:'Photograph of a yarn swatch used to count rows',rights_verified:true,rights_type:'original'}],terminology:'US'};}

test('local draft saves and exports with publication disabled, no reviewers or role escalation',()=>{
  const draft=normalizeOfflineItem({...input(),status:'published',reviewed_by:'spoofed',author_id:'fake'},'editor-1');
  assert.equal(draft.status,'draft'); assert.equal(draft.reviewed_by,undefined); assert.equal(draft.author_id,undefined);
  const exportData=exportWorkspace([draft]);assert.equal(exportData.publication_enabled,false);assert.equal(exportData.format_version,WORKSPACE_FORMAT);
  const parsed=parseWorkspaceText(JSON.stringify(exportData));assert.equal(parsed.drafts[0].status,'draft');assert.equal(parsed.drafts[0].title,input().title);
  assert.equal(summarizeWorkspace([draft]).published,0);
});

test('local workspace roundtrip preserves content but never publishes',()=>{
  const state=new Map();const storage={setItem:(k,v)=>state.set(k,v),getItem:k=>state.get(k)};
  const draft=normalizeOfflineItem(input(),'local');saveLocalWorkspace(storage,[draft]);
  const loaded=loadLocalWorkspace(storage);assert.equal(loaded.error,null);assert.equal(loaded.items.length,1);
  assert.equal(loaded.items[0].status,'draft');assert.equal(state.has(STORAGE_KEY),true);
});

test('unconfigured workspace does not invent a published article or media',()=>{
  const idea=normalizeOfflineItem({...blankDraft(),slug:'a-new-pattern-idea',title:'A new pattern idea',status:'approved',images:[],body:'',test_evidence:{test_status:'physically_tested',human_attested:true}},'x');
  assert.equal(idea.status,'draft');assert(summarizeWorkspace([idea]).needs_work===1);
});

test('keyword handoff imports only research proposals as empty unpublished drafts',()=>{
  const report={format_version:HANDOFF_FORMAT,vertical:'crochet',publication_enabled:false,proposals:[
    {...input(),slug:'crochet-row-counting',status:'published',content_rights:'licensed',test_evidence:{test_status:'physically_tested',human_attested:true}},
    {...input(),slug:'crochet-row-counting',title:'Duplicated keyword'},
    {...input(),slug:'bag-lining-guide',title:'How to line a crochet bag'}]};
  const {drafts,skipped}=parseWorkspaceText(JSON.stringify(report));assert.equal(drafts.length,2);assert.equal(skipped,1);
  assert.equal(drafts[0].status,'draft');assert.equal(drafts[0].body,'');assert.deepEqual(drafts[0].images,[]);
  assert.equal(drafts[0].test_evidence.test_status,'untested');assert.equal(drafts[0].content_rights,'unverified');
  const combined=mergeWorkspaces([drafts[0]],drafts);assert.equal(combined.added,1);assert.equal(combined.skipped,1);
});

test('reject fake or activated reports, crossbrand and forbidden host content',()=>{
  const valid={format_version:HANDOFF_FORMAT,vertical:'crochet',publication_enabled:false,proposals:[input()]};
  for(const mutation of [ {...valid,publication_enabled:true},{...valid,vertical:'recipes'},{...valid,format_version:'unknown'}, {...valid,proposals:[{...input(),description:'recetagenial copy text'}]},{...valid,proposals:[{...input(),images:[{url:'https://example.com/image.png'}]}]} ]) {
    if(mutation.proposals?.[0]?.images?.[0]?.url?.includes('example.com') || mutation.proposals?.[0]?.description?.includes('recetagenial')){
      const response=parseWorkspaceText(JSON.stringify(mutation));assert.equal(response.drafts.length,0);continue;
    }
    assert.throws(()=>parseWorkspaceText(JSON.stringify(mutation)));
  }
  assert.throws(()=>parseWorkspaceText('{broken'),/INVALID_JSON/);
});

test('safe limits, deterministic slugs, no duplicate imports',()=>{
  assert.equal(slugFromTitle('Café Crochet: 10 Easy Ideas'),'cafe-crochet-10-easy-ideas');
  const data={format_version:HANDOFF_FORMAT,vertical:'crochet',publication_enabled:false,proposals:Array.from({length:MAX_DRAFTS+1},(_,i)=>({...input(),slug:`safe-idea-${i}`}))};
  assert.throws(()=>parseWorkspaceText(JSON.stringify(data)),/LIMIT/);
  assert.throws(()=>exportWorkspace(Array.from({length:MAX_DRAFTS+1},()=>input())),/TOO_LARGE/);
});
