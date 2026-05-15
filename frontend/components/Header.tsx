'use client';

import Link from 'next/link';
import { useState, useEffect, Suspense } from 'react';
import { 
  FaFacebookF, 
  FaInstagram, 
  FaPinterestP, 
  FaTiktok, 
  FaYoutube
} from 'react-icons/fa';
import dynamic from 'next/dynamic';
import Cookies from 'js-cookie';
import SearchBar from './SearchBar';
import { useSettings } from '@/context/SettingsContext';

import Image from 'next/image';

const AdminCheck = dynamic(() => import('./AdminCheck'), { ssr: false });

export default function Header() {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const settings = useSettings();

  useEffect(() => {
    let ticking = false;
    const handleScroll = () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          setIsScrolled(window.scrollY > 20);
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    
    // Check for admin session
    const session = Cookies.get('rd_admin') === 'true';
    const localAdmin = localStorage.getItem('rd_admin') === 'true';
    if (session || localAdmin) {
      setIsAdmin(true);
    }

    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const handleAdminQuery = () => {
    localStorage.setItem('rd_admin', 'true');
    Cookies.set('rd_admin', 'true', { expires: 7 }); // Persist for 7 days
    setIsAdmin(true);
  };

  // Navigation Logic: Use dynamic categories if provided in settings, otherwise fallback to defaults
  const settingsCategories = settings?.categories?.map(cat => ({
    label: cat,
    href: `/categoria/${cat.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, '-')}`
  })) || [];

  const defaultCategories = [
    { label: 'Pasteles', href: '/categoria/pasteles' },
    { label: 'Galletas', href: '/categoria/galletas' },
    { label: 'Chocolates', href: '/categoria/chocolates' },
    { label: 'Repostería', href: '/categoria/reposteria' },
    { label: 'Helados', href: '/categoria/helados' },
    { label: 'Postres', href: '/categoria/postres' },
  ];

  const categories = settingsCategories.length > 0 ? settingsCategories : defaultCategories;

  // If settings exist, sanitize URLs but don't filter out "Nuevo Enlace" labels as that confuses users
  const settingsLinks = settings?.navigation_menu
    ?.filter(link => link.label && link.href)
    .map(link => ({
      ...link,
      href: link.href.trim().startsWith('http') || link.href.trim().startsWith('/') 
        ? link.href.trim() 
        : `/${link.href.trim().replace(/\s+/g, '-').toLowerCase()}`,
    }));

  const navLinks = settingsLinks?.length 
    ? settingsLinks 
    : [
        { label: 'Inicio', href: '/' },
        ...categories, // Show dynamic or default categories
        { label: 'Sobre Nosotros', href: '/about' },
      ];

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
    <>
      <Suspense fallback={null}>
        <AdminCheck onAdmin={handleAdminQuery} />
      </Suspense>

      {/* Top Utility Bar - Density Optimized */}
      <div className="w-full bg-cream-base py-1.5 border-b border-cream-dark/50 hidden md:block">
        <div className="max-w-7xl mx-auto px-6 flex justify-between items-center">
          <div className="flex items-center space-x-6 text-xs font-bold uppercase tracking-[0.2em] text-gray-600">
            <Link href="/about" className="hover:text-brand-fresa transition-colors">SOBRE MÍ</Link>
            <Link href="/contact" className="hover:text-brand-fresa transition-colors">CONTACTO</Link>
            {isAdmin && <Link href="/admin" className="text-brand-fresa">PANEL ADMIN</Link>}
          </div>
          <div className="flex items-center space-x-5 text-gray-600">
            {socialLinks.map(({ Icon, href }, i) => {
              const platform = href?.includes('facebook') ? 'Facebook' : 
                               href?.includes('instagram') ? 'Instagram' : 
                               href?.includes('pinterest') ? 'Pinterest' : 
                               href?.includes('youtube') ? 'YouTube' : 'nuestras redes sociales';
              return (
                <a key={i} href={href} target="_blank" rel="noopener noreferrer" className="hover:text-brand-fresa transition-colors" aria-label={`Seguir en ${platform}`}>
                  <Icon size={14} />
                </a>
              );
            })}
          </div>
        </div>
      </div>

      <header className={`sticky top-0 left-0 right-0 z-50 transition-all duration-700 bg-white border-b border-cream-dark/30 ${isScrolled ? 'shadow-lg' : ''}`}>
        <div className="max-w-7xl mx-auto px-6 py-2 md:py-0">
          <div className="flex flex-col items-center relative">
            {/* Collapsible Logo Section - Compact */}
            <div className={`w-full overflow-hidden transition-all duration-700 ease-in-out flex flex-col items-center ${isScrolled ? 'max-h-0 opacity-0 scale-95 pointer-events-none' : 'max-h-[200px] opacity-100 py-3'}`}>
              <Link href="/" className="group flex flex-col items-center space-y-2" aria-label="Volver al inicio - RecetaDolce">
                <div className="relative w-10 h-10 md:w-12 md:h-12 rounded-full overflow-hidden border-2 border-brand-fresa/10 shadow-sm group-hover:border-brand-fresa/30 transition-all duration-700">
                  <Image 
                    src={settings?.site_logo || "/images/brand/logo.png"} 
                    alt={settings?.site_name || "RecetaDolce"} 
                    fill 
                    className="object-cover" 
                    sizes="(max-width: 768px) 40px, 48px" 
                    priority
                    fetchPriority="high"
                  />
                </div>
                <div className="text-center">
                  <h1 className="text-2xl md:text-4xl font-serif text-ink tracking-tightest leading-none">
                    {settings?.site_name ? (
                      <>
                        {settings.site_name.split(' ')[0]}
                        {settings.site_name.includes(' ') && (
                          <span className="text-brand-fresa italic font-light ml-1">
                            {settings.site_name.substring(settings.site_name.indexOf(' ') + 1)}
                          </span>
                        )}
                      </>
                    ) : (
                      <>
                        Receta<span className="text-brand-fresa italic font-light">Dolce</span>
                      </>
                    )}
                  </h1>
                  <p className="text-sm md:text-xs font-bold uppercase tracking-[0.4em] text-gray-600 mt-2">
                    COCINA REAL · SABOR EDITORIAL
                  </p>
                </div>
              </Link>
            </div>

            {/* Sticky Navigation Menu */}
            <nav className={`w-full transition-all duration-500 ease-in-out flex items-center ${
              isScrolled 
                ? 'py-3 justify-between' 
                : 'justify-center mt-0.5 border-t border-cream-base pt-3 pb-3'
            }`}>
              
              {/* Small logo for sticky mode */}
              <Link 
                href="/" 
                className={`transition-all duration-500 flex items-center space-x-3 group ${
                  isScrolled ? 'opacity-100 translate-x-0 w-auto' : 'opacity-0 -translate-x-10 w-0 pointer-events-none'
                }`}
              >
                <div className="relative w-8 h-8 rounded-full overflow-hidden border border-brand-fresa/20">
                  <Image 
                    src={settings?.site_logo || "/images/brand/logo.png"} 
                    alt={settings?.site_name || "RecetaDolce"} 
                    fill 
                    className="object-cover" 
                    sizes="32px" 
                    priority
                  />
                </div>
                <span className="text-xl font-serif text-ink tracking-tighter">
                  {settings?.site_name ? (
                    <>
                      {settings.site_name.split(' ')[0]}
                      {settings.site_name.includes(' ') && (
                        <span className="text-brand-fresa italic ml-1">
                          {settings.site_name.substring(settings.site_name.indexOf(' ') + 1)}
                        </span>
                      )}
                    </>
                  ) : (
                    <>
                      Receta<span className="text-brand-fresa italic">Dolce</span>
                    </>
                  )}
                </span>
              </Link>

              {/* Menu Links */}
              <div className={`hidden md:flex items-center space-x-8 transition-all duration-500 ${isScrolled ? 'flex-1 justify-center' : ''}`}>
                {navLinks.map((link) => (
                  <Link 
                    key={link.href}
                    href={link.href} 
                    className={`text-sm font-bold uppercase tracking-[0.2em] text-ink hover:text-brand-fresa transition-all relative group ${isScrolled ? 'text-xs' : ''}`}
                  >
                    {link.label}
                    <span className="absolute -bottom-2 left-0 w-full h-0.5 bg-brand-fresa scale-x-0 group-hover:scale-x-100 transition-transform duration-500 origin-left" />
                  </Link>
                ))}
              </div>

              {/* Search and Utility */}
              <div className={`flex items-center space-x-4 ${isScrolled ? '' : 'md:pl-4 md:border-l md:border-cream-dark'}`}>
                <SearchBar />
              </div>

              {/* Mobile Trigger for Scrolled Mode */}
              <div className={`md:hidden ${isScrolled ? 'order-first mr-4' : 'absolute top-1/2 -translate-y-1/2 left-4'}`}>
                <button 
                  onClick={() => setMenuOpen(!menuOpen)} 
                  className="text-ink p-2"
                  aria-label={menuOpen ? "Cerrar menú" : "Abrir menú"}
                  aria-expanded={menuOpen}
                >
                  <div className="w-5 h-0.5 bg-current mb-1.5" />
                  <div className="w-5 h-0.5 bg-current mb-1.5" />
                  <div className="w-3 h-0.5 bg-current" />
                </button>
              </div>
            </nav>
          </div>
        </div>


        {/* Mobile Menu Overlay - Full Screen Premium Experience */}
        <div className={`lg:hidden fixed inset-0 z-50 bg-white/95 backdrop-blur-2xl transition-all duration-700 ease-[cubic-bezier(0.23,1,0.32,1)] ${
          menuOpen ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-full'
        }`}>
          <div className="h-full flex flex-col justify-center items-center p-12 relative overflow-hidden">
            {/* Background decorative elements */}
            <div className="absolute top-0 right-0 w-96 h-96 bg-brand-fresa/5 rounded-full -mr-32 -mt-32 blur-3xl opacity-50" />
            <div className="absolute bottom-0 left-0 w-96 h-96 bg-brand-fresa/5 rounded-full -ml-32 -mb-32 blur-3xl opacity-50" />
            
            <nav className="flex flex-col space-y-10 text-center relative z-10 w-full max-w-xs">
              <span className="text-xs font-bold uppercase tracking-[0.4em] text-brand-fresa mb-4 opacity-60">Explorar la Colección</span>
              
              {navLinks.map((link, i) => (
                <Link 
                  key={link.href} 
                  href={link.href} 
                  className="text-4xl font-serif text-ink hover:text-brand-fresa transition-all duration-500 transform hover:scale-105 italic"
                  style={{ transitionDelay: `${i * 100}ms` }}
                  onClick={() => setMenuOpen(false)}
                >
                  {link.label}
                </Link>
              ))}
              
              <div className="pt-12 border-t border-brand-fresa/10 flex flex-col space-y-8">
                  <Link 
                    href={isAdmin ? "/admin" : "/contact"} 
                    className={`text-sm font-bold uppercase tracking-[0.2em] transition-all px-6 py-3 rounded-full ${
                      isAdmin 
                      ? 'bg-brand-fresa text-white shadow-lg shadow-brand-fresa/20' 
                      : 'text-ink hover:text-brand-fresa'
                    }`}
                    onClick={() => setMenuOpen(false)}
                  >
                    {isAdmin ? "Panel de Administración" : "Atención al Cliente"}
                  </Link>
                
                <div className="flex justify-center space-x-8">
                  {socialLinks.map(({ Icon, href }, i) => {
                    const platform = href?.includes('facebook') ? 'Facebook' : 
                                     href?.includes('instagram') ? 'Instagram' : 
                                     href?.includes('pinterest') ? 'Pinterest' : 
                                     href?.includes('youtube') ? 'YouTube' : 'nuestras redes sociales';
                    return (
                      <a 
                        key={i} 
                        href={href} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="text-gray-600 hover:text-brand-fresa transition-all cursor-pointer transform hover:scale-125"
                        aria-label={`Seguir en ${platform}`}
                      >
                        <Icon size={18} />
                      </a>
                    );
                  })}
                </div>
              </div>
            </nav>
            
            <button 
              onClick={() => setMenuOpen(false)}
              className="absolute bottom-16 text-xs font-bold uppercase tracking-[0.3em] text-gray-600 hover:text-ink transition-colors"
            >
              [ Cerrar Galería ]
            </button>
          </div>
        </div>
      </header>
    </>
  );
}
