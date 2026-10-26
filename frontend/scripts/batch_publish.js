
const fs = require('fs');
const path = require('path');

async function publishPosts() {
  const CMS_API_KEY = process.env.CMS_API_KEY;
  const PUBLISH_URL = process.env.PUBLISH_URL || 'http://localhost:3000/api/publish';
  if (!CMS_API_KEY) {
    throw new Error('CMS_API_KEY environment variable is required; do not embed publishing credentials in source control.');
  }
  const parsedUrl = new URL(PUBLISH_URL);
  if (parsedUrl.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(parsedUrl.hostname)) {
    throw new Error('Remote publishing requires an HTTPS PUBLISH_URL.');
  }
  
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
