
const { createClient } = require('@supabase/supabase-js');
const dotenv = require('dotenv');
const path = require('path');

// Load .env.local from the parent directory
dotenv.config({ path: path.resolve(__dirname, '../.env.local') });

async function updateAnalytics() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error('Missing Supabase credentials in .env.local');
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);
  const analyticsId = 'G-X7T6JVMK5V';

  console.log(`Updating Google Analytics ID to: ${analyticsId}...`);

  // Try to update existing record or insert if it doesn't exist
  const { data: existing } = await supabase.from('settings').select('id').single();

  let error;
  if (existing) {
    ({ error } = await supabase
      .from('settings')
      .update({ google_analytics_id: analyticsId })
      .eq('id', existing.id));
  } else {
    ({ error } = await supabase
      .from('settings')
      .insert({ google_analytics_id: analyticsId, site_name: 'RecetaDolce' }));
  }

  if (error) {
    console.error('Error updating settings:', error.message);
  } else {
    console.log('Successfully updated Google Analytics ID in the database!');
  }
}

updateAnalytics();
