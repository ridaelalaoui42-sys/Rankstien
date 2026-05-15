'use client';

import { useState } from 'react';
import { Send, CheckCircle2, Loader2, Mail } from 'lucide-react';

export default function NewsletterBox() {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus('loading');

    try {
      const res = await fetch('/api/newsletter/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Error al suscribirse');

      setStatus('success');
      setMessage(data.message || '¡Revisa tu bandeja de entrada pronto!');
      setEmail('');
    } catch (error: any) {
      setStatus('error');
      setMessage(error.message);
    }
  };

  return (
    <div className="relative overflow-hidden bg-cream-soft/50 border border-brand-fresa/10 p-8 rounded-none">
      {/* Decorative accent */}
      <div className="absolute top-0 left-0 w-1 h-full bg-brand-fresa/40" />

      <div className="pl-4">
        {/* Icon */}
        <div className="inline-flex p-3 bg-brand-fresa/10 rounded-full mb-4">
          <Mail className="w-5 h-5 text-brand-fresa" />
        </div>

        <h3 className="text-xl font-serif text-ink italic mb-2">
          El Club RecetaDolce
        </h3>
        <p className="text-sm text-gray-600 font-serif italic mb-6 leading-relaxed">
          Recetas exclusivas, trucos de chef y novedades directamente en tu bandeja.
        </p>

        {status === 'success' ? (
          <div className="flex flex-col items-start gap-3 py-2">
            <CheckCircle2 className="w-8 h-8 text-brand-fresa" />
            <p className="text-sm font-serif italic text-brand-fresa">{message}</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <input
              type="email"
              required
              placeholder="tu@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-3 bg-white border border-cream-dark text-ink placeholder:text-gray-300 text-sm font-serif outline-none focus:border-brand-fresa/40 transition-colors"
            />
            <button
              type="submit"
              disabled={status === 'loading'}
              className="w-full flex items-center justify-center gap-3 py-3 bg-brand-fresa text-white text-sm font-bold uppercase tracking-[0.3em] hover:bg-brand-red transition-colors duration-500 disabled:opacity-50"
            >
              {status === 'loading' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  <span>Suscribirme</span>
                </>
              )}
            </button>
            {status === 'error' && (
              <p className="text-sm text-brand-fresa font-serif italic">{message}</p>
            )}
            <p className="text-xs text-gray-300 uppercase tracking-widest text-center pt-1">
              Sin spam. Cancela cuando quieras.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
