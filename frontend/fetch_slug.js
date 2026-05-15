require('dotenv').config({path: '.env.local'});
const { createClient } = require('@supabase/supabase-js');
const fs = require('fs');

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const supabase = createClient(supabaseUrl, supabaseKey);

async function run() {
  const { data, error } = await supabase.from('posts').select('*').eq('slug', 'hojaldritos-salados-variados-receta-facil-para-un-aperitivo-infalible').single();
  if (error) { console.error(error); return; }
  fs.writeFileSync('post_content.txt', data.content);
  console.log('Saved to post_content.txt');
}
run();
