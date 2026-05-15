import { getSupabaseAdmin } from '@/lib/supabase';
import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  try {
    const supabase = getSupabaseAdmin();
    const { email } = await req.json();

    if (!email || !email.includes('@')) {
      return NextResponse.json({ error: 'Valid email is required' }, { status: 400 });
    }

    // Check if already subscribed
    const { data: existing } = await supabase
      .from('subscribers')
      .select('id')
      .eq('email', email)
      .single();

    if (existing) {
      return NextResponse.json({ message: 'Already subscribed!' });
    }

    const { error } = await supabase
      .from('subscribers')
      .insert([{ email, status: 'active', source: 'website_footer' }]);

    if (error) throw error;

    return NextResponse.json({ message: 'Welcome to the family!' });
  } catch (error: any) {
    console.error('Subscription Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
