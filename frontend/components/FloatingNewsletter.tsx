'use client';

import { useState, useEffect } from 'react';
import { FaPaperPlane, FaTimes } from 'react-icons/fa';

export default function FloatingNewsletter() {
  const [isVisible, setIsVisible] = useState(false);
  const [isDismissed, setIsDismissed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');

  useEffect(() => {
    setMounted(true);
    
    // Check if dismissed in this session
    const dismissed = sessionStorage.getItem('floating_newsletter_dismissed');
    if (dismissed) {
      setIsDismissed(true);
    }

    let ticking = false;
    const handleScroll = () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          const isSessionDismissed = sessionStorage.getItem('floating_newsletter_dismissed');
          if (window.scrollY > 1000 && !isDismissed && !isSessionDismissed) {
            setIsVisible(true);
          } else {
            setIsVisible(false);
          }
          ticking = false;
        });
        ticking = true;
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [isDismissed]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus('loading');
    
    // Simulate API call
    setTimeout(() => {
      setStatus('success');
      setTimeout(() => {
        setIsDismissed(true);
        setIsVisible(false);
        sessionStorage.setItem('floating_newsletter_dismissed', 'true');
      }, 3000);
    }, 1500);
  };

  if (!mounted) return null;
  if (!isVisible && status !== 'success') return null;

  return (
    <div className={`fixed bottom-4 sm:bottom-8 left-1/2 -translate-x-1/2 z-[100] w-[calc(100%-2rem)] max-w-sm transition-all duration-1000 ease-[cubic-bezier(0.23,1,0.32,1)] ${
      isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-32 pointer-events-none'
    }`}>
      <div className={`bg-white rounded-[2rem] shadow-2xl border border-brand-fresa/10 p-6 md:p-8 w-full max-w-sm md:w-96 relative overflow-hidden group`}>
        {/* Background Accent */}
        <div className="absolute top-0 right-0 w-32 h-32 bg-brand-fresa/5 rounded-full -mr-16 -mt-16 blur-2xl group-hover:bg-brand-fresa/10 transition-colors" />
        
        <button 
          onClick={() => { 
            setIsVisible(false); 
            setIsDismissed(true); 
            sessionStorage.setItem('floating_newsletter_dismissed', 'true');
          }}
          className="absolute top-4 right-4 text-gray-600 hover:text-brand-fresa transition-colors"
          aria-label="Cerrar boletín"
        >
          <FaTimes size={14} />
        </button>

        <div className="relative z-10">
          <span className="text-xs font-bold uppercase tracking-[0.4em] text-brand-fresa mb-2 block">Privilegio Editorial</span>
          <h3 className="text-xl font-serif text-ink mb-3 italic leading-tight">Únete al Círculo Genial</h3>
          <p className="text-xs text-gray-600 font-serif italic mb-5 leading-relaxed">
            Recibe recetas exclusivas y secretos de nuestra cocina directamente en tu bandeja de entrada.
          </p>

          {status === 'success' ? (
            <div className="text-center py-4 animate-fade-up">
              <div className="w-12 h-12 bg-green-50 text-green-500 rounded-full flex items-center justify-center mx-auto mb-4">
                <FaPaperPlane size={16} />
              </div>
              <span className="text-editorial font-medium tracking-widest text-sm uppercase block mb-2 text-brand-fresa">Suscribirse ahora</span>
              <p className="text-xs text-gray-600 mt-2">Tu viaje gastronómico comienza hoy.</p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="relative">
                <input 
                  type="email" 
                  placeholder="Tu correo electrónico..."
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-cream-base border border-cream-dark px-6 py-4 rounded-full text-sm font-serif italic focus:outline-none focus:border-brand-fresa/30 transition-all"
                />
              </div>
              <button 
                type="submit"
                disabled={status === 'loading'}
                className="w-full bg-brand-fresa text-white py-4 rounded-full font-bold uppercase tracking-[0.3em] text-sm hover:bg-brand-red transition-all shadow-lg shadow-brand-fresa/20 flex items-center justify-center space-x-3 group"
              >
                <span>{status === 'loading' ? 'Enviando...' : 'Suscribirse Ahora'}</span>
                <FaPaperPlane className={`text-sm transform transition-transform group-hover:translate-x-1 group-hover:-translate-y-1 ${status === 'loading' ? 'animate-pulse' : ''}`} />
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
