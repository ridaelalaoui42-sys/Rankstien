import { getSupabaseAdmin } from '@/lib/supabase';
import { NextResponse } from 'next/server';
import { Post } from '@/types';

export async function GET() {
  try {
    const supabase = getSupabaseAdmin();
    const { data: posts, error } = await supabase
      .from('posts')
      .select('*')
      .order('created_at', { ascending: false });

    if (error) throw error;

    const auditResults = posts.map((post: Post) => {
      const issues = [];
      const wordCount = post.content ? post.content.split(/\s+/).length : 0;

      if (!post.meta_title || post.meta_title.length < 30) {
        issues.push({
          type: 'warning',
          label: 'Meta Title',
          message: !post.meta_title ? 'Missing meta title' : 'Meta title is too short',
        });
      }

      if (!post.meta_description || post.meta_description.length < 70) {
        issues.push({
          type: 'warning',
          label: 'Meta Description',
          message: !post.meta_description ? 'Missing meta description' : 'Meta description is too short',
        });
      }

      if (wordCount < 300) {
        issues.push({
          type: 'info',
          label: 'Word Count',
          message: `Content is thin (${wordCount} words). Aim for 300+`,
        });
      }

      if (!post.hero_image) {
        issues.push({
          type: 'error',
          label: 'Featured Image',
          message: 'Missing featured image',
        });
      } else if (!post.image_alt) {
        issues.push({
          type: 'warning',
          label: 'Image Alt',
          message: 'Missing alt text for featured image',
        });
      }

      if (!post.recipe_schema) {
        issues.push({
          type: 'error',
          label: 'Recipe Schema',
          message: 'Missing JSON-LD Recipe Schema',
        });
      }

      if (!post.excerpt) {
        issues.push({
          type: 'info',
          label: 'Excerpt',
          message: 'Missing post excerpt',
        });
      }

      const score = Math.max(0, 100 - (issues.length * 15));

      return {
        id: post.id,
        title: post.title,
        slug: post.slug,
        score,
        issues,
        wordCount,
      };
    });

    return NextResponse.json(auditResults);
  } catch (error: any) {
    console.error('Audit Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
