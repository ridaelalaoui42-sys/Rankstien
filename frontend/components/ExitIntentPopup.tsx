
'use client';

import { useState, useEffect } from 'react';
import { FaTimes } from 'react-icons/fa';
import NewsletterForm from './NewsletterForm';

export default function ExitIntentPopup() {
  const [isVisible, setIsVisible] = useState(false);
  const [hasShown, setHasShown] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    // Check if user has already seen it in this session
    const shown = sessionStorage.getItem('exit_popup_shown');
    if (shown) {
      setHasShown(true);
    }

    const handleMouseLeave = (e: MouseEvent) => {
      if (e.clientY < 0 && !hasShown) {
        setIsVisible(true);
        setHasShown(true);
        sessionStorage.setItem('exit_popup_shown', 'true');
      }
    };

    document.addEventListener('mouseleave', handleMouseLeave);
    return () => document.removeEventListener('mouseleave', handleMouseLeave);
  }, [hasShown]);

  if (!mounted || !isVisible) return null;

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-6 animate-fade-in">
      <div className="absolute inset-0 bg-ink/60 backdrop-blur-md" onClick={() => setIsVisible(false)} />
      
      <div className="relative w-full max-w-2xl bg-cream-base rounded-[3rem] overflow-hidden shadow-2xl animate-scale-up">
        <button 
          onClick={() => setIsVisible(false)}
          className="absolute top-8 right-8 text-ink/60 hover:text-brand-fresa transition-colors z-10"
          aria-label="Cerrar ventana"
        >
          <FaTimes size={24} />
        </button>

        <div className="grid grid-cols-1 md:grid-cols-2">
          <div className="relative h-64 md:h-auto bg-brand-fresa/10 overflow-hidden">
             <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-10">
                <span className="text-editorial text-brand-fresa mb-4">No te vayas aún</span>
                <h3 className="text-4xl font-serif text-ink mb-6 italic">¿Un postre <br /> de cortesía?</h3>
                <div className="w-12 h-px bg-brand-fresa/30" />
             </div>
             <div className="absolute -bottom-20 -right-20 w-64 h-64 bg-brand-fresa/5 rounded-full blur-3xl" />
          </div>

          <div className="p-8 md:p-16 flex flex-col justify-center">
            <h4 className="text-sm font-bold uppercase tracking-[0.4em] text-gray-600 mb-6">Únete al Círculo Genial</h4>
            <p className="text-lg text-gray-600 font-serif italic mb-10 leading-relaxed">
              Recibe nuestras recetas secretas y guías gastronómicas exclusivas directamente en tu bandeja de entrada.
            </p>
            <NewsletterForm />
            <p className="text-xs text-gray-600 mt-8 text-center uppercase tracking-widest">
              Prometemos solo elegancia, nada de spam.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
