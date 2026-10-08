export const DEFAULT_RECIPE_FALLBACK = 'https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282752/RecetaDolce/mediterranean_ingredients_fallback.jpg';

interface PostImageCandidate {
  hero_image?: string | null;
  featured_image?: string | null;
  recipe_schema?: any;
}

/**
 * Validates whether a candidate string is a valid renderable image URL.
 */
export function isValidImageUrl(source: unknown): source is string {
  if (!source || typeof source !== 'string') return false;
  const val = source.trim();
  if (!val || val === 'PLACEHOLDER' || val.toLowerCase() === 'null' || val.toLowerCase() === 'undefined') {
    return false;
  }
  return val.startsWith('/') || val.startsWith('data:image/') || /^https?:\/\//i.test(val);
}

/**
 * Extracts a valid image URL from a recipe_schema object.
 */
function extractSchemaImage(schema: any): string | null {
  if (!schema) return null;
  let parsed = schema;
  if (typeof schema === 'string') {
    try {
      parsed = JSON.parse(schema);
    } catch {
      return null;
    }
  }

  const img = parsed?.image;
  if (Array.isArray(img) && img.length > 0) {
    const first = img[0];
    if (isValidImageUrl(first)) return first.trim();
    if (first && typeof first === 'object' && isValidImageUrl(first.url)) return first.url.trim();
  } else if (isValidImageUrl(img)) {
    return img.trim();
  } else if (img && typeof img === 'object' && isValidImageUrl(img.url)) {
    return img.url.trim();
  }

  return null;
}

/**
 * Resolves the best available image URL for a recipe post.
 * Prioritizes hero_image -> featured_image -> recipe_schema.image -> fallbackSrc.
 */
export function getPostImageUrl(
  post?: PostImageCandidate | null,
  fallbackSrc: string = DEFAULT_RECIPE_FALLBACK
): string {
  if (!post) return fallbackSrc;

  if (isValidImageUrl(post.hero_image)) {
    return post.hero_image.trim();
  }

  if (isValidImageUrl(post.featured_image)) {
    return post.featured_image.trim();
  }

  const schemaImage = extractSchemaImage(post.recipe_schema);
  if (schemaImage) {
    return schemaImage;
  }

  return fallbackSrc;
}
