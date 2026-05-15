require('dotenv').config({path: '../.env'});
require('dotenv').config({path: '.env.local', override: true});
const { createClient } = require('@supabase/supabase-js');

const oldSupabase = createClient(
  process.env.RECETAGENIAL_SUPABASE_URL,
  process.env.RECETAGENIAL_SUPABASE_KEY
);

const newSupabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY // Need to make sure this is available, or use NEXT_PUBLIC_SUPABASE_ANON_KEY if insert is allowed, but service role is better.
);

async function run() {
  const slug = 'hojaldritos-salados-variados-receta-facil-para-un-aperitivo-infalible';
  console.log(`Fetching ${slug} from RecetaGenial...`);
  const { data, error } = await oldSupabase.from('posts').select('*').eq('slug', slug).single();
  if (error) { console.error('Error fetching:', error); return; }
  
  console.log(`Publishing ${slug} to RecetaDolce directly via DB...`);
  
  // Basic category mapping if needed based on app/api/publish/route.ts logic
  // 'Aperitivos y Tapas' -> 'postres-y-dulces' or 'pasteles' depending on the Dolce structure.
  // Actually, Dolce expects: ['postres-y-dulces', 'pasteles', 'tartas-y-bizcochos', 'galletas-y-masas']
  // If it's a legacy savory post, maybe it's best to map it to 'postres-y-dulces' or just leave it as is if category isn't restricted by DB schema.
  
  const { error: insertError } = await newSupabase.from('posts').upsert({
    slug: data.slug,
    title: data.title,
    content: data.content,
    excerpt: data.excerpt,
    hero_image: data.hero_image,
    category: 'postres-y-dulces', // Map all legacy to a default Dolce category or keep original if valid. Let's just use 'postres-y-dulces' to avoid constraints, or data.category if no constraints exist.
    meta_description: data.meta_description,
    keyword: data.keyword,
    pinterest_pin_id: data.pinterest_pin_id,
    recipe_schema: data.recipe_schema,
    created_at: data.created_at,
    updated_at: data.updated_at
  }, { onConflict: 'slug' });
  
  if (insertError) {
    console.error(`Failed to publish:`, insertError);
  } else {
    console.log(`Successfully published ${slug} to the new DB!`);
  }
}
run();
