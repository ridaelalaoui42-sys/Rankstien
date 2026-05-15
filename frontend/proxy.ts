import { NextRequest, NextResponse } from 'next/server';

export default function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Protect /admin routes (exclude login page)
  if (pathname.startsWith('/admin') && pathname !== '/admin/login') {
    const session = req.cookies.get('rd_admin_session');
    if (!session || session.value !== 'authenticated') {
      const loginUrl = req.nextUrl.clone();
      loginUrl.pathname = '/admin/login';
      return NextResponse.redirect(loginUrl);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/admin/:path*'],
};

