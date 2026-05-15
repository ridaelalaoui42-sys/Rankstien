
const fs = require('fs');
const path = require('path');

async function publishPosts() {
  const CMS_API_KEY = 'aura_cms_secure_receta_2026';
  const PUBLISH_URL = 'http://localhost:3000/api/publish';
  
  const files = fs.readdirSync('.').filter(f => f.startsWith('temp_post_') && f.endsWith('.json'));
  
  console.log(`Found ${files.length} posts to publish...`);
  
  for (const file of files) {
    console.log(`Publishing ${file}...`);
    try {
      const content = JSON.parse(fs.readFileSync(file, 'utf8'));
      
      const response = await fetch(PUBLISH_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-KEY': CMS_API_KEY
        },
        body: JSON.stringify(content)
      });
      
      const result = await response.json();
      if (response.ok) {
        console.log(`Successfully published: ${content.title} -> ${result.url}`);
      } else {
        console.error(`Failed to publish ${file}:`, result.error);
      }
    } catch (err) {
      console.error(`Error processing ${file}:`, err.message);
    }
  }
}

publishPosts();
