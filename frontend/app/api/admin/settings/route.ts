import { NextRequest, NextResponse } from 'next/server';
import { getSupabaseAdmin } from '@/lib/supabase';
import { revalidatePath } from 'next/cache';

export const dynamic = 'force-dynamic';

export async function GET() {
  const supabase = getSupabaseAdmin();
  try {
    const { data, error } = await supabase
      .from('settings')
      .select('*')
      .eq('id', 'global')
      .single();

    if (error) {
      // If table doesn't exist or row doesn't exist, provide a helpful error
      if (error.code === 'PGRST116') {
         return NextResponse.json({ 
           error: 'Settings not found. Please ensure the "settings" table exists and has a row with id "global".',
           needs_setup: true 
         }, { status: 404 });
      }
      throw error;
    }

    return NextResponse.json(data);
  } catch (error: any) {
    console.error('Error fetching settings:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    // Check authentication
    const session = req.cookies.get('rd_admin_session');
    if (!session || session.value !== 'authenticated') {
      return NextResponse.json({ error: 'No autorizado' }, { status: 401 });
    }

    const body = await req.json();
    
    // Remove id from body to avoid conflicts if it exists
    const { id, created_at, ...settingsData } = body;

    const supabase = getSupabaseAdmin();
    const { data, error } = await supabase
      .from('settings')
      .upsert({ 
        ...settingsData,
        id: 'global',
        updated_at: new Date().toISOString()
      })
      .select()
      .single();

    if (error) throw error;

    // Revalidate the entire site to reflect changes in Header/Footer
    revalidatePath('/', 'layout');

    return NextResponse.json(data);
  } catch (error: any) {
    console.error('Error saving settings:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

