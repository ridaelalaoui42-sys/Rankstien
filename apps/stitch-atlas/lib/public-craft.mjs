import {studioConfig} from './studio-server.mjs';
const validSlug=/^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export async function publishedCraftArticle(slug) {
  if(!validSlug.test(slug))return null;
  const config=studioConfig();if(!config)return null;
  const url=config.url+'/rest/v1/craft_posts?select=slug,title,description,body,kind,category,images,steps,materials,terminology,hook_size_mm,yarn_weight,gauge,finished_dimensions,source_links,published_at&status=eq.published&slug=eq.'+encodeURIComponent(slug)+'&limit=1';
  try{
    const headers={apikey:config.key,Accept:'application/json'};if(config.key.startsWith('eyJ'))headers.Authorization='Bearer '+config.key;
    const response=await fetch(url,{headers,next:{revalidate:300}});
    if(!response.ok)return null;
    const posts=await response.json();return posts?.[0]||null;
  }catch{return null;}
}
