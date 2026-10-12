import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

export async function GET(request: NextRequest) {
  try {
    const supabase = createClient(supabaseUrl, supabaseServiceKey);
    const { searchParams } = new URL(request.url);
    const domain = searchParams.get('domain');

    let query = supabase
      .from('posts')
      .select('id, pinterest_pin_id, pinterest_pin_url, status, domain', { count: 'exact' });

    if (domain) {
      query = query.eq('domain', domain);
    }

    const { data: posts, count, error } = await query;

    if (error) {
      return NextResponse.json(
        { error: error.message },
        { status: 500 }
      );
    }

    // Count pins by status
    const pinStats = {
      total_posts: count || 0,
      with_pins: posts?.filter(p => p.pinterest_pin_id || p.pinterest_pin_url).length || 0,
      without_pins: posts?.filter(p => !p.pinterest_pin_id && !p.pinterest_pin_url).length || 0,
      published: posts?.filter(p => p.status === 'published').length || 0,
      draft: posts?.filter(p => p.status === 'draft').length || 0,
      by_domain: {} as Record<string, any>,
    };

    // Group by domain
    if (posts) {
      for (const post of posts) {
        const d = post.domain || 'unknown';
        if (!pinStats.by_domain[d]) {
          pinStats.by_domain[d] = {
            total: 0,
            with_pins: 0,
            without_pins: 0,
            published: 0,
            draft: 0,
          };
        }
        pinStats.by_domain[d].total++;
        if (post.pinterest_pin_id || post.pinterest_pin_url) {
          pinStats.by_domain[d].with_pins++;
        } else {
          pinStats.by_domain[d].without_pins++;
        }
        if (post.status === 'published') {
          pinStats.by_domain[d].published++;
        } else if (post.status === 'draft') {
          pinStats.by_domain[d].draft++;
        }
      }
    }

    return NextResponse.json({
      ...pinStats,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('Failed to fetch pin stats:', error);
    return NextResponse.json(
      { error: 'Failed to fetch pin statistics' },
      { status: 500 }
    );
  }
}
