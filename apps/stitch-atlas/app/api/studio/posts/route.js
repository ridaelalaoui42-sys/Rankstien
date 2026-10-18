import {getEditor,listEditorialPosts,insertEditorialDraft,parseLimitedRequest,apiFailure} from '../../../../lib/studio-server.mjs';
export const dynamic='force-dynamic';
export async function GET(request){try{const session=await getEditor(request);return Response.json({role:session.role,posts:await listEditorialPosts(session)},{headers:{'cache-control':'no-store'}})}catch(e){return apiFailure(e)}}
export async function POST(request){try{const session=await getEditor(request);const payload=await parseLimitedRequest(request);const created=await insertEditorialDraft(session,payload);return Response.json({posts:created},{status:201,headers:{'cache-control':'no-store'}})}catch(e){return apiFailure(e)}}
