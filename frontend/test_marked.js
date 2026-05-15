const marked = require('marked');
const sanitizeHtml = require('sanitize-html');

async function test() {
  const raw = `<img src="https://example.com/img.jpg" alt="alt text">\n\nSome text.\n\n<iframe src="https://pinterest.com"></iframe>`;
  const parsed = await marked.parse(raw);
  console.log('Marked output:');
  console.log(parsed);
  
  const sanitized = sanitizeHtml(parsed, {
    allowedTags: sanitizeHtml.defaults.allowedTags.concat(['img', 'iframe']),
    allowedAttributes: {
      img: ['src', 'alt'],
      iframe: ['src']
    }
  });
  console.log('Sanitized output:');
  console.log(sanitized);
}

test();
