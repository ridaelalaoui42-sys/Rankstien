import { NextRequest, NextResponse } from 'next/server';

const ODYSSEUS_URL = process.env.ODYSSEUS_URL || 'http://127.0.0.1:7000';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { action, mode, config } = body;

    if (!action) {
      return NextResponse.json(
        { error: 'action is required' },
        { status: 400 }
      );
    }

    let endpoint = '';
    let method = 'POST';

    switch (action) {
      case 'start':
        if (!mode) {
          return NextResponse.json(
            { error: 'mode is required for start action' },
            { status: 400 }
          );
        }
        endpoint = `/api/rankstein/control/start/rankstein/${mode}`;
        break;

      case 'stop':
        if (!mode) {
          return NextResponse.json(
            { error: 'mode is required for stop action' },
            { status: 400 }
          );
        }
        endpoint = `/api/rankstein/control/stop/${mode}`;
        break;

      case 'status':
        endpoint = `/api/rankstein/control/status`;
        method = 'GET';
        break;

      default:
        return NextResponse.json(
          { error: `Unknown action: ${action}` },
          { status: 400 }
        );
    }

    const response = await fetch(`${ODYSSEUS_URL}${endpoint}`, {
      method,
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
      ...(method === 'POST' && config ? { body: JSON.stringify(config) } : {}),
      cache: 'no-store',
    });

    if (!response.ok) {
      const errorText = await response.text();
      return NextResponse.json(
        { error: `Odysseus error: ${response.status}`, details: errorText },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Campaign control error:', error);
    return NextResponse.json(
      { error: 'Failed to execute campaign control action' },
      { status: 500 }
    );
  }
}
