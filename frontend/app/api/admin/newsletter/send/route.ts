import { getSupabaseAdmin } from '@/lib/supabase';
import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  try {
    const supabase = getSupabaseAdmin();
    const { subject, message, isTest } = await req.json();

    if (!message) {
      return NextResponse.json({ error: 'Message is required' }, { status: 400 });
    }

    // 1. Fetch all active subscribers
    const { data: subscribers, error } = await supabase
      .from('subscribers')
      .select('email')
      .eq('status', 'active');

    if (error) throw error;

    if (!subscribers || subscribers.length === 0) {
      return NextResponse.json({ message: 'No active subscribers found.' });
    }

    // 2. In a real world app, you would integrate with Resend, SendGrid, etc. here.
    // For now, we log the action and simulate success.
    console.log(`Blighting newsletter to ${subscribers.length} users:`, { subject, message });

    // Simulate delay
    await new Promise(resolve => setTimeout(resolve, 1000));

    return NextResponse.json({ 
      success: true, 
      message: `Newsletter "${subject || 'Actualización'}" enviada correctamente a ${subscribers.length} suscriptores.`,
      recipientCount: subscribers.length
    });
  } catch (error: any) {
    console.error('Newsletter Blast Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
