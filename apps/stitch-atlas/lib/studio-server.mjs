import {normalizeDraft} from './editorial-contract.mjs';

const blockedProjects = new Set(['hokcljsrrnjxzgdhjice','xjvmnmfczvwkjiasirsl']);
const jsonHeaders = {'content-type':'application/json','cache-control':'no-store'};

export function studioConfig() {
  const raw = process.env.NEXT_PUBLIC_CROCHET_SUPABASE_URL || '';
  const key = process.env.NEXT_PUBLIC_CROCHET_SUPABASE_ANON_KEY || '';
  if (!raw || !key) return null;
  let url;
  try { url = new URL(raw); } catch { throw Error('INVALID_CROCHET_DATABASE_URL'); }
  const project = url.hostname.split('.')[0];
  if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.supabase\.co$/.test(url.hostname) || blockedProjects.has(project) || url.pathname!=='/') {
    throw Error('STITCH_ATLAS_MUST_USE_DEDICATED_SUPABASE_PROJECT');
  }
  return {url:url.origin,key};
}
export const errorJson = (message,status=400) => Response.json({error:message},{status,headers:jsonHeaders});

async function scopedFetch(config, path, accessToken, options={}) {
  const url = config.url + path;
  const headers = {
    apikey:config.key,
    Authorization:'Bearer '+accessToken,
    Accept:'application/json',
    ...options.headers,
  };
  return fetch(url,{...options,headers,cache:'no-store',redirect:'error'});
}

async function restJson(response) {
  const raw = await response.text();
  if (!response.ok) {
    let message='EDITORIAL_REQUEST_FAILED';
    try { message=JSON.parse(raw).message||message; } catch {}
    throw Object.assign(Error(message),{status:response.status});
  }
  if (!raw) return null;
  return JSON.parse(raw);
}

export async function getEditor(request) {
  const config=studioConfig();
  if (!config) throw Object.assign(Error('EDITORIAL_BACKEND_NOT_CONFIGURED'),{status:503});
  const header=request.headers.get('authorization')||'';
  const found=/^Bearer ([A-Za-z0-9_\-.]+)$/.exec(header);
  if (!found) throw Object.assign(Error('AUTHORIZATION_REQUIRED'),{status:401});
  const token=found[1];
  const userResponse=await scopedFetch(config,'/auth/v1/user',token);
  if (!userResponse.ok) throw Object.assign(Error('INVALID_USER_SESSION'),{status:401});
  const user=await userResponse.json();
  if (!user?.id || !/^[0-9a-f-]{36}$/i.test(user.id)) throw Object.assign(Error('INVALID_USER_SESSION'),{status:401});
  const rows=await restJson(await scopedFetch(config,'/rest/v1/craft_staff?select=role&user_id=eq.'+encodeURIComponent(user.id)+'&limit=1',token));
  if (!Array.isArray(rows)||!rows.length) throw Object.assign(Error('EDITORIAL_STAFF_ACCESS_REQUIRED'),{status:403});
  return {config,token,user_id:user.id,role:rows[0].role};
}

export async function listEditorialPosts(session) {
  const url='/rest/v1/craft_posts?select=id,slug,title,description,kind,category,status,content_rights,terminology,images,steps,materials,source_links,stitch_count_checks,test_evidence,hook_size_mm,yarn_weight,gauge,finished_dimensions,body,seo_keyword,research_evidence,author_id,reviewed_by,reviewer_notes,updated_at,published_at&order=updated_at.desc&limit=100';
  return restJson(await scopedFetch(session.config,url,session.token));
}

export async function insertEditorialDraft(session,payload) {
  const draft=normalizeDraft(payload);
  return restJson(await scopedFetch(session.config,'/rest/v1/craft_posts',session.token,{method:'POST',headers:{'Content-Type':'application/json',Prefer:'return=representation'},body:JSON.stringify({...draft,author_id:session.user_id,status:'draft'})}));
}
export async function editEditorialDraft(session,id,payload) {
  const draft=normalizeDraft(payload);
  const query='/rest/v1/craft_posts?id=eq.'+encodeURIComponent(id)+'&author_id=eq.'+encodeURIComponent(session.user_id)+'&status=in.(draft,needs_changes)';
  const result=await restJson(await scopedFetch(session.config,query,session.token,{method:'PATCH',headers:{'Content-Type':'application/json',Prefer:'return=representation'},body:JSON.stringify(draft)}));
  if (!Array.isArray(result)||!result.length) throw Object.assign(Error('DRAFT_NOT_EDITABLE'),{status:409});
  return result;
}
export async function transitionEditorial(session,id,action,notes='') {
  const def={
    submit:['craft_submit_post',{p_post_id:id}],
    approve:['craft_review_post',{p_post_id:id,p_decision:'approve',p_notes:notes}],
    request_changes:['craft_review_post',{p_post_id:id,p_decision:'request_changes',p_notes:notes}],
    archive:['craft_archive_post',{p_post_id:id}],
    publish:['craft_publish_post',{p_post_id:id}],
  }[action];
  if (!def) throw Object.assign(Error('UNKNOWN_EDITORIAL_ACTION'),{status:400});
  if (action==='publish' && process.env.CROCHET_PUBLISHING_ENABLED!=='true') throw Object.assign(Error('PUBLICATION_DISABLED_UNTIL_LAUNCH'),{status:403});
  return restJson(await scopedFetch(session.config,'/rest/v1/rpc/'+def[0],session.token,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(def[1])}));
}
export async function parseLimitedRequest(request,maxBytes=250000) {
  const raw=await request.text();
  if (Buffer.byteLength(raw,'utf8')>maxBytes) throw Object.assign(Error('REQUEST_TOO_LARGE'),{status:413});
  try { return JSON.parse(raw); } catch {throw Object.assign(Error('INVALID_JSON'),{status:400});}
}
export function apiFailure(error) {
  const known=error?.status;
  const status=Number.isInteger(known)&&known>=400&&known<=599?known:500;
  // Do not echo internal Supabase, authorization or SQL details to unauthenticated clients.
  return errorJson(status===500?'EDITORIAL_SERVER_ERROR':String(error.message||'EDITORIAL_ERROR').slice(0,160),status);
}
