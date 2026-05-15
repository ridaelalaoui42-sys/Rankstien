'use client';
import Link from 'next/link';
import { FaFacebookF, FaInstagram, FaPinterestP, FaTiktok, FaYoutube } from 'react-icons/fa';
import NewsletterForm from './NewsletterForm';
import { useSettings } from '@/context/SettingsContext';

// Removed static SOCIAL_LINKS as they are now dynamic

export default function Footer() {
  const settings = useSettings();

  const socialLinks = settings
    ? [
        { Icon: FaFacebookF, href: settings.facebook_url },
        { Icon: FaInstagram, href: settings.instagram_url },
        { Icon: FaPinterestP, href: settings.pinterest_url },
        { Icon: FaYoutube, href: settings.youtube_url },
      ].filter(l => l.href)
    : [
        { Icon: FaFacebookF, href: 'https://facebook.com' },
        { Icon: FaInstagram, href: 'https://instagram.com' },
        { Icon: FaPinterestP, href: 'https://pinterest.com' },
        { Icon: FaYoutube, href: 'https://youtube.com' },
      ];

  return (
    <footer className="bg-white border-t border-cream-dark/30 py-6 md:py-8">
      <div className="max-w-7xl mx-auto px-6 text-center">
        {/* Logo */}
        <Link href="/" className="inline-block mb-4">
          <h2 className="text-2xl md:text-3xl font-serif text-ink tracking-tightest leading-none">
            {settings?.site_name?.split(' ')[0] || 'Receta'}<span className="text-brand-fresa italic font-light ml-1">{settings?.site_name?.split(' ')[1] || 'Dolce'}</span>
          </h2>
        </Link>

        {/* Description */}
        <p className="max-w-xl mx-auto text-gray-600 text-sm leading-relaxed mb-6 font-serif italic">
          {settings?.site_description || "Descubre el placer de cocinar con recetas explicadas paso a paso, trucos de cocina y los mejores ingredientes para que tus platos sean siempre de escándalo."}
        </p>
        
        {/* Links */}
        <nav className="flex flex-wrap justify-center gap-x-8 md:gap-x-12 gap-y-4 mb-8 text-xs md:text-sm font-bold uppercase tracking-[0.3em] text-gray-600">
          <Link href="/" className="hover:text-brand-fresa transition-colors">INICIO</Link>
          <Link href="/about" className="hover:text-brand-fresa transition-colors">SOBRE MÍ</Link>
          <Link href="/contact" className="hover:text-brand-fresa transition-colors">CONTACTO</Link>
          <Link href="/seguridad-alimentaria" className="hover:text-brand-fresa transition-colors">SEGURIDAD ALIMENTARIA</Link>
          <Link href="/guia-higiene" className="hover:text-brand-fresa transition-colors">GUÍA DE HIGIENE</Link>
          <Link href="/privacy" className="hover:text-brand-fresa transition-colors">PRIVACIDAD</Link>
          <Link href="/cookies" className="hover:text-brand-fresa transition-colors">COOKIES</Link>
        </nav>

        {/* Social */}
        <div className="flex justify-center space-x-6 mb-8">
          {socialLinks.map(({ Icon, href }, i) => {
            const safeHref = href || '';
            const label = safeHref.includes('facebook') ? 'Facebook' : 
                          safeHref.includes('instagram') ? 'Instagram' : 
                          safeHref.includes('pinterest') ? 'Pinterest' : 
                          safeHref.includes('youtube') ? 'YouTube' : 'Red Social';
            return (
              <a 
                key={i} 
                href={href} 
                target="_blank"
                rel="noopener noreferrer"
                className="text-gray-600 hover:text-brand-fresa transition-colors transform hover:scale-110"
                aria-label={`Síguenos en ${label}`}
              >
                <Icon size={16} />
              </a>
            );
          })}
        </div>

        {/* Copyright */}
        <div className="pt-6 border-t border-cream-soft/50 text-sm uppercase tracking-[0.5em] text-gray-600">
          © <span suppressHydrationWarning>{new Date().getFullYear()}</span> {settings?.site_name?.toUpperCase() || 'RecetaDolce'} STUDIO. TODOS LOS DERECHOS RESERVADOS.
        </div>
      </div>
    </footer>

  );
}
