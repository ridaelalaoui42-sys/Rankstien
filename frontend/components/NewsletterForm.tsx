
'use client';
import { useState } from 'react';
import { FaHeart, FaPaperPlane } from 'react-icons/fa';

export default function NewsletterForm() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    
    setLoading(true);
    
    try {
      const res = await fetch('/api/newsletter/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      if (res.ok) {
        setSent(true);
        setEmail('');
      } else {
        const data = await res.json();
        console.error('Subscription error:', data.error);
      }
    } catch (err) {
      console.error('Newsletter error:', err);
    } finally {
      setTimeout(() => setLoading(false), 1000); // Slight delay for effect
    }
  };

  if (sent) {
    return (
      <div className="animate-fade-up flex flex-col items-center text-center p-8 bg-white/50 backdrop-blur-md rounded-3xl border border-brand-fresa/10">
        <div className="w-16 h-16 bg-brand-fresa/10 rounded-full flex items-center justify-center text-brand-fresa mb-6 animate-bounce-small">
          <FaHeart size={24} />
        </div>
        <h4 className="text-xl font-serif text-ink mb-2 italic">¡Ya eres parte de la mesa!</h4>
        <p className="text-sm uppercase tracking-[0.3em] text-gray-600 font-bold">
          Revisa tu bandeja para el regalo de bienvenida.
        </p>
      </div>
    );
  }

  return (
    <div className="group">
      <form onSubmit={handleSubmit} className="relative" aria-label="Suscripción gourmet">
        <div className="relative overflow-hidden rounded-full bg-white/50 backdrop-blur-sm border border-brand-fresa/10 group-focus-within:border-brand-fresa transition-all duration-500 shadow-sm group-focus-within:shadow-xl">
          <input
            type="email"
            name="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Tu correo de gourmet..."
            required
            aria-label="Email"
            className="w-full bg-transparent py-5 pl-8 pr-32 text-sm outline-none placeholder:text-gray-600 placeholder:italic font-serif"
          />
          <button
            type="submit"
            disabled={loading}
            className="absolute right-2 top-2 bottom-2 px-8 rounded-full bg-ink text-white text-xs font-bold uppercase tracking-[0.2em] hover:bg-brand-fresa transition-all duration-500 disabled:opacity-50 flex items-center space-x-3 overflow-hidden group/btn"
          >
            {loading ? (
              <span className="flex items-center space-x-2">
                <span className="w-1 h-1 bg-white rounded-full animate-bounce" />
                <span className="w-1 h-1 bg-white rounded-full animate-bounce [animation-delay:0.2s]" />
                <span className="w-1 h-1 bg-white rounded-full animate-bounce [animation-delay:0.4s]" />
              </span>
            ) : (
              <>
                <span>Unirse</span>
                <FaPaperPlane size={8} className="group-hover/btn:translate-x-1 group-hover/btn:-translate-y-1 transition-transform" />
              </>
            )}
          </button>
        </div>
      </form>
      <div className="mt-6 flex items-center justify-center md:justify-start space-x-3 text-sm font-bold uppercase tracking-[0.3em] text-gray-600">
        <div className="w-1 h-1 bg-brand-fresa/30 rounded-full" />
        <span>Privacidad absoluta</span>
        <div className="w-1 h-1 bg-brand-fresa/30 rounded-full" />
        <span>Sin Spam</span>
      </div>
    </div>
  );
}
