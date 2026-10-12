import { NextRequest, NextResponse } from 'next/server';

const ODYSSEUS_URL = process.env.ODYSSEUS_URL || 'http://127.0.0.1:7000';

export async function GET(request: NextRequest) {
  try {
    const response = await fetch(`${ODYSSEUS_URL}/api/rankstein/control/status`, {
      headers: {
        'Accept': 'application/json',
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: `Odysseus error: ${response.status}` },
        { status: response.status }
      );
    }

    const data = await response.json();

    // Extract key metrics for the dashboard
    const metrics = {
      alive: data.operator?.alive || false,
      supervisor_running: data.rankstein?.processes?.supervisor?.alive || false,
      production_running: data.rankstein?.processes?.production?.alive || false,
      queue: data.rankstein?.queue || { pending: 0, processing: 0, retry: 0, dlq_size: 0 },
      domains: data.rankstein?.domains || [],
      actions: data.rankstein?.actions || {},
      timestamp: new Date().toISOString(),
    };

    return NextResponse.json(metrics);
  } catch (error) {
    console.error('Failed to fetch operator status:', error);
    return NextResponse.json(
      { error: 'Failed to fetch operator status' },
      { status: 500 }
    );
  }
}
