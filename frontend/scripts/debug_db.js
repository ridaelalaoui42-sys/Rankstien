
const { createClient } = require('@supabase/supabase-js');
require('dotenv').config({ path: '.env.local' });

async function debugSupabase() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  console.log('Connecting to:', url);
  
  const supabase = createClient(url, key);
  const adminSupabase = createClient(url, serviceKey);

  // 1. Check with Anon Key (Public)
  console.log('\n--- Checking with ANON KEY (Public) ---');
  const { data: publicData, error: publicError } = await supabase
    .from('posts')
    .select('id, title, status')
    .eq('status', 'published');
  
  if (publicError) console.error('Public Fetch Error:', publicError.message);
  else console.log(`Found ${publicData?.length || 0} published posts.`);

  // 2. Check with Service Key (Bypassing RLS)
  console.log('\n--- Checking with SERVICE ROLE KEY (Admin) ---');
  const { data: adminData, error: adminError } = await adminSupabase
    .from('posts')
    .select('id, title, status');
  
  if (adminError) console.error('Admin Fetch Error:', adminError.message);
  else {
    console.log(`Total posts in DB: ${adminData?.length || 0}`);
    adminData?.forEach(p => console.log(`- [${p.status}] ${p.title}`));
  }

  // 3. Check Settings
  console.log('\n--- Checking SETTINGS ---');
  const { data: settings, error: settingsError } = await supabase
    .from('settings')
    .select('*')
    .eq('id', 'global')
    .single();
    
  if (settingsError) console.error('Settings Error:', settingsError.message);
  else console.log('Settings found for:', settings.site_name);
}

debugSupabase();
