const { marked } = require('marked');
const sanitizeHtml = require('sanitize-html');

async function test() {
  const content = `<img src="https://hokcljsrrnjxzgdhjice.supabase.co/storage/v1/object/public/recipe-images/hero-images/hojaldritos-salados-variados.jpg" alt="aperitivos salados" class="w-full rounded-xl shadow-lg mb-8">\n\nLos hojaldritos salados son, sin duda...`;
  
  const parsed = await marked.parse(content);
  console.log('Marked:', parsed);
  
  const sanitized = sanitizeHtml(parsed, {
    allowedTags: sanitizeHtml.defaults.allowedTags.concat([
      'a', 'img', 'figure', 'figcaption', 'video', 'source',
      'iframe', 'details', 'summary', 'mark', 'del', 'ins',
      'sub', 'sup', 'abbr', 'time', 'picture', 'span'
    ]),
    allowedAttributes: {
      img: ['src', 'alt', 'class']
    }
  });
  console.log('Sanitized:', sanitized);
}
test();
