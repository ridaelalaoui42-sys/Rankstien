/**
 * Canonical category mapping.
 * Maps DB category values (which can be compound like "arroces y paellas")
 * to real category page slugs that exist at /categoria/{slug}.
 */

export const CATEGORIES = {
  pasteles:    { label: 'Pasteles', keywords: ['tarta', 'bizcocho', 'pastel', 'cake', 'cheesecake', 'pie'] },
  galletas:    { label: 'Galletas', keywords: ['galleta', 'cookie', 'macaron', 'pasta', 'crujiente'] },
  chocolates:  { label: 'Chocolates', keywords: ['chocolate', 'cacao', 'trufa', 'bombón', 'ganache', 'praliné'] },
  reposteria:  { label: 'Repostería', keywords: ['bollería', 'hojaldre', 'masa', 'crema', 'merengue', 'soufflé'] },
  helados:     { label: 'Helados', keywords: ['helado', 'sorbete', 'granizado', 'frío', 'gelato'] },
  postres:     { label: 'Postres', keywords: ['postre', 'dulce', 'fruta', 'mousse', 'flan', 'natilla', 'pudding'] },
} as const;

export type CategorySlug = keyof typeof CATEGORIES;

const BASE_URL = 'https://RecetaDolce.com';

/**
 * Maps a raw DB category string to the closest real category slug.
 * e.g. "arroces y paellas" → "arroces"
 *      "platos principales / carnes" → "carnes"
 *      "postres y repostería" → "postres"
 */
export function getCategorySlug(dbCategory: string | null | undefined): CategorySlug {
  if (!dbCategory) return 'postres'; // fallback

  const lower = dbCategory.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

  // Direct match first
  if (lower in CATEGORIES) return lower as CategorySlug;

  // Keyword match
  for (const [slug, meta] of Object.entries(CATEGORIES)) {
    // Check if any keyword appears in the DB category string
    if (meta.keywords.some(kw => lower.includes(kw))) {
      return slug as CategorySlug;
    }
    // Check if the slug itself appears in the DB category string
    if (lower.includes(slug)) {
      return slug as CategorySlug;
    }
  }

  return 'postres'; // ultimate fallback
}

/**
 * Returns the full canonical URL for a category.
 */
export function getCategoryUrl(dbCategory: string | null | undefined): string {
  return `${BASE_URL}/categoria/${getCategorySlug(dbCategory)}`;
}

/**
 * Returns the display label for a category.
 */
export function getCategoryLabel(dbCategory: string | null | undefined): string {
  const slug = getCategorySlug(dbCategory);
  return CATEGORIES[slug].label;
}
