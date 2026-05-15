require('dotenv').config({path: '../.env'});
const { createClient } = require('@supabase/supabase-js');
const fs = require('fs');

const supabaseUrl = process.env.RECETAGENIAL_SUPABASE_URL;
const supabaseKey = process.env.RECETAGENIAL_SUPABASE_KEY;
const supabase = createClient(supabaseUrl, supabaseKey);

async function run() {
  const { data, error } = await supabase.from('posts').select('*').eq('slug', 'hojaldritos-salados-variados-receta-facil-para-un-aperitivo-infalible').single();
  if (error) { console.error(error); return; }
  fs.writeFileSync('post_content_recetagenial.txt', data.content);
  console.log('Saved to post_content_recetagenial.txt');
}
run();
