
'use client';

import SafeImage from './SafeImage';
import Link from 'next/link';
import { FaFacebook, FaInstagram, FaPinterest, FaYoutube } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';
import NewsletterBox from './newsletter/NewsletterBox';
import { useSettings } from '@/context/SettingsContext';
import { SITE_IMAGES } from '@/lib/siteImages';

interface FeaturedPost {
  title: string;
  slug: string;
  hero_image: string;
}

interface SidebarProps {
  featuredPosts?: FeaturedPost[];
}

export default function Sidebar({ featuredPosts = [] }: SidebarProps) {
  const settings = useSettings();

  const socialLinks = [
    { Icon: FaFacebook, href: settings?.facebook_url },
    { Icon: FaInstagram, href: settings?.instagram_url },
    { Icon: FaPinterest, href: settings?.pinterest_url },
    { Icon: FaXTwitter, href: settings?.twitter_url },
    { Icon: FaYoutube, href: settings?.youtube_url },
  ].filter(l => l.href);

  return (
    <aside className="space-y-8">
      {/* About Me Section - Compact Editorial Style */}
      <div className="bg-white p-5 md:p-6 text-center rounded-[2rem] border border-gray-50 shadow-sm relative overflow-hidden group">
        <div className="absolute top-0 left-0 w-full h-1 bg-brand-fresa" />
        <h3 className="text-xs font-bold uppercase tracking-[0.4em] text-ink/40 mb-4">Directora Editorial</h3>
        <div className="relative w-24 h-24 mx-auto mb-4 rounded-full overflow-hidden border-4 border-cream-base shadow-lg">
          <SafeImage
            src={SITE_IMAGES.author}
            alt="Isabella Dolce"
            fill
            sizes="96px"
            className="object-cover group-hover:scale-105 transition-transform duration-1000"
          />
        </div>
        <h4 className="text-xl font-serif italic text-ink mb-3">Isabella Dolce</h4>
        <p className="font-serif italic text-gray-600 leading-relaxed mb-6 text-xs">
          "Mi pasión es la cocina tradicional con un toque moderno. Aquí comparto mis secretos para que cocines como un profesional."
        </p>
        <Link href="/about" className="inline-block text-xs font-bold uppercase tracking-widest text-brand-fresa border-b border-brand-fresa/10 pb-1 hover:border-brand-fresa transition-all">
          DESCUBRE MI HISTORIA
        </Link>
      </div>

      {/* Popular Recipes Spotlight — Dynamic from Supabase */}
      {featuredPosts.length > 0 && (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-bold uppercase tracking-[0.5em] text-ink/40 whitespace-nowrap">Destacados</h3>
          <div className="flex-1 h-px bg-gray-50" />
        </div>
        <div className="space-y-4">
          {featuredPosts.map((item, i) => (
            <Link key={item.slug || i} href={`/${item.slug}`} className="flex gap-4 group">
              <div className="relative w-16 h-16 flex-shrink-0 overflow-hidden rounded-2xl shadow-sm transition-all duration-700">
                <SafeImage src={item.hero_image} alt={item.title} fill sizes="64px" className="object-cover group-hover:scale-110 transition-transform duration-1000" />
              </div>
              <div className="flex flex-col justify-center">
                <h4 className="font-serif text-md text-ink group-hover:text-brand-fresa transition-colors leading-snug">
                  {item.title}
                </h4>
              </div>
            </Link>
          ))}
        </div>
      </div>
      )}


      {/* E-E-A-T Section: Trust & Safety */}
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-bold uppercase tracking-[0.5em] text-ink/40 whitespace-nowrap">Seguridad</h3>
          <div className="flex-1 h-px bg-gray-50" />
        </div>
        <div className="bg-cream-base/50 p-6 rounded-[2rem] border border-cream-dark/20">
          <h4 className="text-sm font-bold text-ink mb-3 uppercase tracking-wider">Compromiso E-E-A-T</h4>
          <p className="text-[10px] text-gray-600 font-serif italic mb-4 leading-relaxed">
            Nuestras recetas siguen los protocolos de seguridad alimentaria de la <span className="text-brand-fresa font-bold">AESAN</span> y normativas europeas.
          </p>
          <div className="space-y-2">
            <Link 
              href="/seguridad-alimentaria" 
              className="block text-[10px] font-bold uppercase tracking-widest text-brand-fresa hover:underline"
            >
              Marco Legislativo →
            </Link>
            <Link 
              href="/guia-higiene" 
              className="block text-[10px] font-bold uppercase tracking-widest text-brand-fresa hover:underline"
            >
              Guía de Higiene Profesional →
            </Link>
          </div>
        </div>
      </div>

      {/* Categories Area */}
      <div className="space-y-8">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-bold uppercase tracking-[0.5em] text-ink/40 whitespace-nowrap">Explorar</h3>
          <div className="flex-1 h-px bg-gray-50" />
        </div>
        <div className="grid grid-cols-1 gap-3">
          {[
            { label: 'Pasteles', slug: 'pasteles' },
            { label: 'Galletas', slug: 'galletas' },
            { label: 'Chocolates', slug: 'chocolates' },
            { label: 'Repostería', slug: 'reposteria' },
            { label: 'Helados', slug: 'helados' },
            { label: 'Postres', slug: 'postres' }
          ].map((cat) => (
            <Link 
              key={cat.slug} 
              href={`/categoria/${cat.slug}`}
              className="px-4 py-3 bg-white hover:bg-brand-fresa hover:text-white transition-all duration-500 flex justify-between items-center group border border-gray-50 rounded-xl shadow-sm"
            >
              <span className="text-sm font-bold uppercase tracking-[0.2em]">{cat.label}</span>
              <span className="opacity-0 group-hover:opacity-100 transition-all transform group-hover:translate-x-1 text-base leading-none">→</span>
            </Link>
          ))}
        </div>
      </div>

      {/* Newsletter Widget */}
      <div className="bg-ink p-8 rounded-[2.5rem] text-center shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-32 h-32 bg-brand-fresa/20 rounded-full blur-3xl -mr-16 -mt-16" />
        <NewsletterBox />
      </div>
    </aside>
  );
}
