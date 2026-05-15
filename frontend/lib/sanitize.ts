import sanitizeHtml from 'sanitize-html';

/**
 * Server-safe HTML sanitizer.
 * Uses sanitize-html (pure JS) instead of isomorphic-dompurify (needs jsdom).
 * This works on Vercel serverless without crashing.
 */
export function sanitize(dirty: string): string {
  return sanitizeHtml(dirty, {
    allowedTags: sanitizeHtml.defaults.allowedTags.concat([
      'a', 'img', 'figure', 'figcaption', 'video', 'source',
      'iframe', 'details', 'summary', 'mark', 'del', 'ins',
      'sub', 'sup', 'abbr', 'time', 'picture', 'span'
    ]),
    allowedAttributes: {
      ...sanitizeHtml.defaults.allowedAttributes,
      img: ['src', 'alt', 'title', 'width', 'height', 'loading', 'decoding', 'class', 'style'],
      a: ['href', 'name', 'target', 'rel', 'class', 'id', 'title'],
      iframe: ['src', 'width', 'height', 'frameborder', 'allow', 'allowfullscreen', 'loading'],
      video: ['src', 'controls', 'width', 'height', 'poster', 'preload'],
      source: ['src', 'type'],
      time: ['datetime'],
      '*': ['class', 'id', 'style'],
    },
    // Downgrade <h1> in body content to <h2> to maintain single H1 per page
    transformTags: {
      'h1': 'h2',
      'a': (tagName, attribs) => {
        const href = attribs.href || '';
        const isExternal = (href.startsWith('http') || href.startsWith('//')) && 
                          !href.includes('RecetaDolce.com') && 
                          !href.includes('recetadolce.com');
        
        const finalAttribs = {
          ...attribs,
          // Use a class that we know exists in our CSS or plain styling
          // Adding cursor-pointer explicitly to ensure it feels clickable
          class: `${attribs.class || ''} editorial-link`.trim(),
        };

        if (isExternal) {
          return {
            tagName: 'a',
            attribs: {
              ...finalAttribs,
              target: '_blank',
              rel: 'noopener noreferrer nofollow'
            }
          };
        }

        return {
          tagName: 'a',
          attribs: finalAttribs
        };
      },
    },
    allowedIframeHostnames: ['www.youtube.com', 'youtube.com', 'player.vimeo.com', 'assets.pinterest.com'],
    allowedSchemes: ['http', 'https', 'mailto', 'tel', 'sms', 'data'],
    allowProtocolRelative: true,
    allowedSchemesByTag: {
      a: ['http', 'https', 'mailto', 'tel', 'sms'],
    },
    allowedSchemesAppliedToAttributes: ['href', 'src', 'cite'],
  });
}
