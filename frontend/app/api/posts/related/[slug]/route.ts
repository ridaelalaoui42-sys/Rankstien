import { getSupabaseAdmin } from '@/lib/supabase';
import { NextResponse } from 'next/server';

export async function GET(
  req: Request,
  { params }: { params: Promise<{ slug: string }> }
) {
  try {
    const supabase = getSupabaseAdmin();
    const { slug } = await params;

    // Get current post to find its category
    const { data: currentPost } = await supabase
      .from('posts')
      .select('category_id, id')
      .eq('slug', slug)
      .single();

    if (!currentPost) {
      return NextResponse.json({ error: 'Post not found' }, { status: 404 });
    }

    // Fetch related posts in same category, excluding current
    const { data: related, error } = await supabase
      .from('posts')
      .select('id, title, slug, hero_image, excerpt, category_id, difficulty, prep_time')
      .eq('category_id', currentPost.category_id)
      .neq('id', currentPost.id)
      .eq('is_published', true)
      .limit(3);

    if (error) throw error;

    return NextResponse.json(related);
  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
