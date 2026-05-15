import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Explicit image hostnames (wildcard ** is a security risk)
  images: {
    // Production currently returns 402 for /_next/image optimizer requests.
    // Serve source URLs directly so valid images render instead of payment errors.
    unoptimized: true,
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'hokcljsrrnjxzgdhjice.supabase.co',
        pathname: '/storage/v1/object/public/**',
      },
      {
        protocol: 'https',
        hostname: 'xjvmnmfczvwkjiasirsl.supabase.co',
        pathname: '/storage/v1/object/public/**',
      },
      {
        protocol: 'https',
        hostname: 'res.cloudinary.com',
      },
      {
        protocol: 'https',
        hostname: 'images.unsplash.com',
      },
      {
        protocol: 'https',
        hostname: 'i.pravatar.cc',
      },
    ],
    formats: ['image/avif', 'image/webp'],
    minimumCacheTTL: 60 * 60 * 24 * 7, // 7 days
  },

  // Security headers for all routes
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-XSS-Protection', value: '1; mode=block' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains; preload' },
        ],
      },
      {
        // Cache static assets aggressively
        source: '/images/(.*)',
        headers: [
          { key: 'Cache-Control', value: 'public, max-age=31536000, immutable' },
        ],
      },
    ];
  },

  // Redirects for common URL variants
  async redirects() {
    return [
      { source: '/sobre-nosotros', destination: '/about', permanent: true },
      { source: '/nuestra-historia', destination: '/about', permanent: true },
      { source: '/sobre%20nosotros', destination: '/about', permanent: true },
    ];
  },

  // Redirect trailing slashes
  trailingSlash: false,

  // Compression
  compress: true,

  // Powered-by header removal
  poweredByHeader: false,

  // Optimization settings
  reactStrictMode: true,
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production' ? { exclude: ['error', 'warn'] } : false,
  },

  serverExternalPackages: ['sanitize-html', 'marked'],
  // Advanced performance optimizations
  experimental: {
    optimizePackageImports: [
      'react-icons',
      'lucide-react',
      'framer-motion',
      'clsx',
      'tailwind-merge'
    ],
    cssChunking: false,
  },
  // Empty turbopack config — acknowledges Next.js 16 default bundler.
  // Polyfill reduction is handled by the browserslist in package.json.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
