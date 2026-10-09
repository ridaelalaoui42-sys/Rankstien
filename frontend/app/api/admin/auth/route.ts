export const dynamic = 'force-dynamic';
import { NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  let password = '';
  try {
    const body = await req.json();
    password = typeof body?.password === 'string' ? body.password : '';
  } catch {
    return NextResponse.json({ error: 'Solicitud inválida' }, { status: 400 });
  }

  const correct = process.env.ADMIN_PASSWORD;
  if (!correct) {
    return NextResponse.json(
      { error: 'ADMIN_PASSWORD no está configurado en el servidor.' },
      { status: 500 },
    );
  }
  if (password.trim() !== correct.trim()) {
    return NextResponse.json({ error: 'Contraseña incorrecta' }, { status: 401 });
  }

  const isHttps = req.nextUrl.protocol === 'https:' || req.headers.get('x-forwarded-proto') === 'https';
  const isSecure = process.env.NODE_ENV === 'production' && isHttps;

  // Set a session cookie valid for 7 days
  const res = NextResponse.json({ success: true });
  res.cookies.set('rd_admin_session', 'authenticated', {
    httpOnly: true,
    secure: isSecure,
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: '/',
  });
  // Public cookie for UI state (not for security)
  res.cookies.set('rd_admin', 'true', {
    httpOnly: false,
    secure: isSecure,
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 7,
    path: '/',
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ success: true });
  // Expire both cookies explicitly (more reliable than .delete in some runtimes)
  res.cookies.set('rd_admin_session', '', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 0,
    path: '/',
  });
  res.cookies.set('rd_admin', '', {
    httpOnly: false,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 0,
    path: '/',
  });
  return res;
}
