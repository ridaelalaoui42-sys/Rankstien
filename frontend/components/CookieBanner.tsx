'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import Cookies from 'js-cookie';

export default function CookieBanner() {
  const [show, setShow] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const consent = Cookies.get('rg_cookie_consent');
    if (!consent) {
      const timer = setTimeout(() => setShow(true), 2000);
      return () => clearTimeout(timer);
    }
  }, []);

  const acceptCookies = () => {
    Cookies.set('rg_cookie_consent', 'true', { expires: 365 });
    setShow(false);
  };

  if (!mounted || !show) return null;

  return (
    <div className="fixed bottom-10 left-6 right-6 md:left-10 md:right-auto md:max-w-md z-[100] animate-fade-up">
      <div className="bg-white/90 backdrop-blur-2xl p-8 rounded-[2.5rem] shadow-[0_20px_50px_rgba(189,30,45,0.15)] border border-brand-fresa/10 relative overflow-hidden group">
        {/* Decorative corner */}
        <div className="absolute top-0 right-0 w-24 h-24 bg-brand-fresa/5 rounded-full -mr-12 -mt-12 blur-2xl" />
        
        <div className="relative z-10">
          <div className="flex items-center space-x-3 mb-4">
            <div className="w-2 h-2 rounded-full bg-brand-fresa animate-pulse" />
            <span className="text-sm font-bold uppercase tracking-[0.3em] text-brand-fresa">Experiencia Genial</span>
          </div>
          
          <h4 className="text-xl font-serif text-ink mb-4 italic">Un toque de dulzor digital</h4>
          
          <p className="text-xs text-gray-600 leading-loose mb-8">
            Utilizamos cookies propias y de terceros para que su viaje por nuestra gastronomía sea fluido y personalizado. 
            Consulte nuestra <Link href="/cookies" className="text-brand-fresa underline underline-offset-4 decoration-brand-fresa/30 hover:decoration-brand-fresa transition-all">Política de Cookies</Link> para más detalles.
          </p>
          
          <div className="flex items-center space-x-4">
            <button 
              onClick={acceptCookies}
              className="px-10 py-4 bg-brand-fresa text-white text-xs font-bold uppercase tracking-[0.3em] rounded-full hover:bg-ink transition-all duration-500 shadow-lg shadow-brand-fresa/20"
            >
              Aceptar Todo
            </button>
            <button 
              onClick={() => setShow(false)}
              className="text-xs font-bold uppercase tracking-[0.3em] text-gray-600 hover:text-brand-fresa transition-colors"
            >
              Cerrar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
