import type { Metadata } from "next";
import { Playfair_Display, Outfit, Great_Vibes } from "next/font/google";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import ExitIntentPopup from "@/components/ExitIntentPopup";
import SchemaMarkup from '@/components/SchemaMarkup';
import FloatingNewsletter from '@/components/FloatingNewsletter';
import CookieBanner from '@/components/CookieBanner';
import { getSettings } from "@/lib/settings";
import Script from "next/script";
import { SettingsProvider } from "@/context/SettingsContext";


const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  display: 'swap',
});

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
  display: 'swap',
});

const greatVibes = Great_Vibes({
  weight: "400",
  variable: "--font-great-vibes",
  subsets: ["latin"],
  display: 'swap',
});

const BASE_URL = 'https://RecetaDolce.com';

export async function generateMetadata() {
  const settings = await getSettings();
  
  const siteName = settings?.site_name || 'RecetaDolce';
  const siteDesc = settings?.site_description || 'Recetas auténticas de cocina española: tapas, paella, postres y más.';
  
  return {
    metadataBase: new URL(BASE_URL),
    title: {
      default: `${siteName} | Cocina Española de Alta Gama`,
      template: `%s | ${siteName}`,
    },
    description: siteDesc,
    keywords: settings?.seo_keywords || ['recetas españolas', 'cocina española', 'tapas', 'paella', 'postres'],
    authors: [{ name: `${siteName} Editorial` }],
    creator: siteName,
    publisher: siteName,
    robots: { index: true, follow: true, googleBot: { index: true, follow: true } },
    openGraph: {
      type: 'website',
      locale: 'es_ES',
      url: BASE_URL,
      siteName: siteName,
      title: `${siteName} | Cocina Española de Alta Gama`,
      description: siteDesc,
      images: [{
        url: '/og-image.jpg',
        width: 1200,
        height: 630,
        alt: `${siteName} - Recetas de cocina española auténtica`,
      }],
    },
    twitter: {
      card: 'summary_large_image',
      title: `${siteName} | Cocina Española de Alta Gama`,
      description: siteDesc,
      images: ['/og-image.jpg'],
    },
    icons: {
      icon: [
        { url: '/favicon.png', type: 'image/png' },
      ],
      apple: '/apple-touch-icon.png',
    },
    manifest: '/site.webmanifest',
  };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const settings = await getSettings();

  return (
    <html lang="es" className={`${playfair.variable} ${outfit.variable} ${greatVibes.variable} scroll-smooth`} suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://fonts.googleapis.com" />
        <link rel="dns-prefetch" href="https://fonts.gstatic.com" />
        
        <link rel="preconnect" href="https://res.cloudinary.com" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://res.cloudinary.com" />
        
        <link rel="preconnect" href="https://xjvmnmfczvwkjiasirsl.supabase.co" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://xjvmnmfczvwkjiasirsl.supabase.co" />
        {settings?.google_analytics_id && (
          <link rel="preconnect" href="https://www.googletagmanager.com" />
        )}
        {settings?.ads_enabled && (
          <link rel="preconnect" href="https://pagead2.googlesyndication.com" crossOrigin="anonymous" />
        )}
        {settings?.google_analytics_id && (
          <>
            <Script
              src={`https://www.googletagmanager.com/gtag/js?id=${settings.google_analytics_id}`}
              strategy="lazyOnload"
            />
            <Script id="google-analytics" strategy="lazyOnload">
              {`
                window.dataLayer = window.dataLayer || [];
                function gtag(){dataLayer.push(arguments);}
                gtag('js', new Date());
                gtag('config', '${settings.google_analytics_id}');
              `}
            </Script>
          </>
        )}
        {settings?.ads_enabled && settings?.adsense_client_id && (
          <Script
            async
            src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${settings.adsense_client_id}`}
            crossOrigin="anonymous"
            strategy="lazyOnload"
          />
        )}
      </head>
      <body className="bg-cream-base text-ink antialiased min-h-screen flex flex-col font-sans">
        {settings?.custom_head_code && (
          <div 
            id="custom-head-code-injection" 
            className="hidden" 
            dangerouslySetInnerHTML={{ __html: settings.custom_head_code }} 
            suppressHydrationWarning
          />
        )}
        <SettingsProvider settings={settings}>
          <SchemaMarkup 
            type="Organization" 
            data={{
              "@context": "https://schema.org",
              "@graph": [
                {
                  "@type": "Organization",
                  "@id": `${BASE_URL}/#organization`,
                  "name": settings?.site_name || "RecetaDolce",
                  "url": BASE_URL,
                  "logo": {
                    "@type": "ImageObject",
                    "url": settings?.site_logo || "https://xjvmnmfczvwkjiasirsl.supabase.co/storage/v1/object/public/recipe-images/hero-home.png",
                    "width": "512",
                    "height": "512"
                  },
                  "sameAs": [
                    settings?.facebook_url,
                    settings?.instagram_url,
                    settings?.pinterest_url,
                    settings?.tiktok_url,
                    settings?.youtube_url
                  ].filter(Boolean).length > 0 ? [
                    settings?.facebook_url,
                    settings?.instagram_url,
                    settings?.pinterest_url,
                    settings?.tiktok_url,
                    settings?.youtube_url
                  ].filter(Boolean) : [
                    "https://facebook.com/RecetaDolce",
                    "https://instagram.com/RecetaDolce_oficial",
                    "https://pinterest.com/RecetaDolce_studio",
                    "https://tiktok.com/@RecetaDolce",
                    "https://youtube.com/@RecetaDolce"
                  ],
                  "contactPoint": {
                    "@type": "ContactPoint",
                    "email": "ridaelalaoui42@gmail.com",
                    "contactType": "customer support"
                  },
                  "knowsAbout": [
                    "Seguridad Alimentaria",
                    "Gastronomía Española",
                    "Higiene en la Cocina",
                    "Nutrición",
                    "Técnicas de Cocina Profesional"
                  ],
                  "publishingPrinciples": `${BASE_URL}/seguridad-alimentaria`
                },
                {
                  "@type": "WebSite",
                  "@id": `${BASE_URL}/#website`,
                  "url": BASE_URL,
                  "name": settings?.site_name || "RecetaDolce",
                  "description": settings?.site_description || "El Santuario de la Cocina Española de Alta Gama",
                  "publisher": { "@id": `${BASE_URL}/#organization` },
                  "potentialAction": {
                    "@type": "SearchAction",
                    "target": {
                      "@type": "EntryPoint",
                      "urlTemplate": `${BASE_URL}/search?q={search_term_string}`
                    },
                    "query-input": "required name=search_term_string"
                  },
                  "inLanguage": "es-ES"
                }
              ]
            }} 
          />
          <Header />
          <main className="flex-grow overflow-x-hidden">
            {children}
          </main>
          <Footer />
          <ExitIntentPopup />
          <FloatingNewsletter />
          <CookieBanner />
          {settings?.custom_footer_code && (
            <div dangerouslySetInnerHTML={{ __html: settings.custom_footer_code }} />
          )}
        </SettingsProvider>
      </body>
    </html>
  );
}

