
const { createClient } = require('@supabase/supabase-js');
const dotenv = require('dotenv');
const path = require('path');

dotenv.config({ path: path.resolve(__dirname, '../.env.local') });

async function updateHeadCode() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error('Missing Supabase credentials in .env.local');
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);
  const headCode = '<script type="text/javascript" src="https://app.secureprivacy.ai/script/69ee47c03c5995a25fbb2338.js"></script>';

  console.log('Updating Custom Head Code...');

  const { data: existing } = await supabase.from('settings').select('id, custom_head_code').single();

  let error;
  if (existing) {
    // Append if there's already code, or just set it
    const newCode = existing.custom_head_code && !existing.custom_head_code.includes(headCode) 
      ? existing.custom_head_code + '\n' + headCode 
      : headCode;

    ({ error } = await supabase
      .from('settings')
      .update({ custom_head_code: newCode })
      .eq('id', existing.id));
  } else {
    ({ error } = await supabase
      .from('settings')
      .insert({ custom_head_code: headCode, site_name: 'RecetaDolce' }));
  }

  if (error) {
    console.error('Error updating settings:', error.message);
  } else {
    console.log('Successfully updated Custom Head Code in the database!');
  }
}

updateHeadCode();
