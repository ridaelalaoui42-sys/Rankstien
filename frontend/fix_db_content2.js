require('dotenv').config({path: '.env.local'});
const { createClient } = require('@supabase/supabase-js');

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseKey) {
  console.error("Missing Supabase credentials");
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

async function run() {
  const { data, error } = await supabase.from('posts').select('id, slug, content');
  if (error) { console.error(error); return; }
  let count = 0;
  for (const post of data) {
    if (post.content && (post.content.includes('\\"') || post.content.includes('\\[') || post.content.includes('\\]') || post.content.includes('\\n'))) {
      console.log('Post ' + post.slug + ' has escaped chars.');
      // Fix double escaped quotes
      let newContent = post.content.replace(/\\"/g, '"');
      // Fix escaped brackets
      newContent = newContent.replace(/\\\[/g, '[');
      newContent = newContent.replace(/\\\]/g, ']');
      // If the content itself was double escaped entirely, let's also remove \\n and make them \n
      newContent = newContent.replace(/\\n/g, '\n');
      
      await supabase.from('posts').update({ content: newContent }).eq('id', post.id);
      count++;
    }
  }
  console.log('Fixed ' + count + ' posts.');
}
run();
