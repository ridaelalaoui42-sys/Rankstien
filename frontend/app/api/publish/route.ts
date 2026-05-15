export const dynamic = 'force-dynamic';
import { NextResponse } from 'next/server';
import { getSupabaseAdmin } from '@/lib/supabase';

function generateSlug(title: string): string {
  return title
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '') // remove accents
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
}

export async function POST(request: Request) {
  try {
    const API_KEY = process.env.CMS_API_KEY;
    const supabaseAdmin = getSupabaseAdmin();

    // 1. Validate API Key
    const authHeader = request.headers.get('X-API-KEY');
    if (!API_KEY || authHeader !== API_KEY) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const body = await request.json();
    const {
      title,
      content,
      excerpt,
      category, // Old field, we'll map this to category_id
      category_id,
      hero_image,
      meta_title,
      seo_title,
      meta_description,
      seo_description,
      geo_location,
      recipe_schema,
      faq_schema,
      keywords,
      status,
      is_published,
      difficulty,
      estimated_cost,
      prep_time,
      cook_time,
      cooking_time,
      servings,
      ingredients,
      instructions,
      image_alt,
      chef_tip,
      author,
    } = body;

    if (!title || !content) {
      return NextResponse.json(
        { error: 'title and content are required' },
        { status: 400 }
      );
    }

    // Category Mapping (Fallback if only category name is provided)
    let finalCategoryId = category_id;
    if (!finalCategoryId && category) {
      const categoryMap: Record<string, string> = {
        'Pasteles': 'a9c68090-df28-4f3b-8106-4362eebac177',
        'Galletas': '3170b1ef-bd71-4d0c-9515-961930fbd2d8',
        'Chocolates': '75af6eb9-24e7-4dc8-823d-c0aa73b2f878',
        'Repostería': '1ad0e55e-9319-4c71-b265-8e4cf97ffde2',
        'Helados': 'fdbd192e-6625-4431-8665-f52ece22f2ee',
        'Postres': '2aa1c230-57b2-4488-861a-2d4e84a1a0ea'
      };
      finalCategoryId = categoryMap[category] || '2aa1c230-57b2-4488-861a-2d4e84a1a0ea'; // Default to Postres
    }

    // Helper to strip HTML and truncate
    const createExcerpt = (text: string, length: number = 160) => {
      const stripped = text.replace(/<[^>]*>?/gm, '').trim();
      return stripped.length > length ? stripped.substring(0, length) + '...' : stripped;
    };

    // 2. Generate unique slug (with accent normalization for Spanish)
    const baseSlug = generateSlug(title);
    let slug = baseSlug;

    // Check for slug collision
    const { data: existing } = await supabaseAdmin
      .from('posts')
      .select('slug')
      .eq('slug', baseSlug)
      .maybeSingle();

    if (existing) {
      slug = `${baseSlug}-${Date.now()}`;
    }

    // Smart defaults
    const finalExcerpt = excerpt || createExcerpt(content);
    const finalMetaTitle = seo_title || meta_title || title;
    const finalMetaDesc = seo_description || meta_description || finalExcerpt;
    const finalImageAlt = image_alt || title;
    const finalChefTip = chef_tip || `Para que esta receta de ${title.toLowerCase()} te quede perfecta, asegúrate de usar ingredientes frescos y de calidad. ¡El secreto está en el cariño que le pongas!`;

    // 3. Insert into Supabase with service role
    const { data, error } = await supabaseAdmin
      .from('posts')
      .insert([
        {
          title,
          slug,
          content,
          excerpt: finalExcerpt,
          category_id: finalCategoryId || '2aa1c230-57b2-4488-861a-2d4e84a1a0ea',
          hero_image: hero_image || null,
          is_published: is_published !== undefined ? is_published : (status === 'published'),
          seo_title: finalMetaTitle,
          seo_description: finalMetaDesc,
          geo_location: geo_location || null,
          recipe_schema: recipe_schema || null,
          faq: faq_schema || null,
          keywords: keywords || title.split(' ').filter((w: string) => w.length > 3),
          difficulty: difficulty || 'Media',
          estimated_cost: estimated_cost || 'Medio',
          prep_time: prep_time || 20,
          cook_time: cook_time || 30,
          cooking_time: cooking_time || `PT${(prep_time || 20) + (cook_time || 30)}M`,
          servings: servings || '4 raciones',
          ingredients: ingredients || [],
          instructions: instructions || [],
          image_alt: finalImageAlt,
          chef_tip: finalChefTip,
          author: author || 'Isabella Dolce',
        },
      ])
      .select()
      .single();

    if (error) {
      console.error('Supabase insert error:', error);
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json(
      {
        success: true,
        message: 'Receta publicada correctamente',
        id: data.id,
        slug,
        url: `/${slug}`,
      },
      { status: 201 }
    );
  } catch (err: any) {
    console.error('Publish API error:', err);
    return NextResponse.json(
      { error: err.message || 'Invalid request body' },
      { status: 400 }
    );
  }
}
