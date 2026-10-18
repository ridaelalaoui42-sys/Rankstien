import EditorialStudio from '../../components/EditorialStudio';
import OfflineDraftStudio from '../../components/OfflineDraftStudio';
export const metadata={title:'Editorial Studio · Local Draft Workspace',description:'Build original, unpublished Stitch Atlas crochet editorial drafts. Local-only workspace until a dedicated CMS database is available.',robots:{index:false,follow:false}};
export default function EditorialWorkspace(){
  // A complete dedicated Supabase config activates the authenticated production CMS.
  // Missing config activates ONLY the clearly labeled local drafting sandbox.
  const offline=!process.env.NEXT_PUBLIC_CROCHET_SUPABASE_URL&&!process.env.NEXT_PUBLIC_CROCHET_SUPABASE_ANON_KEY;
  return <main id="main"><section className="container studio-container">{offline?<OfflineDraftStudio/>:<EditorialStudio/>}</section></main>;
}
