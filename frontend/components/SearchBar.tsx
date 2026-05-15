
'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { FaSearch, FaTimes } from 'react-icons/fa';

export default function SearchBar() {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      router.push(`/search?q=${encodeURIComponent(query.trim())}`);
      setIsOpen(false);
      setQuery('');
    }
  };

  return (
    <div className="relative">
      <button 
        onClick={() => setIsOpen(true)}
        className="text-gray-600 hover:text-brand-fresa transition-colors p-2" 
        aria-label="Abrir buscador"
      >
        <FaSearch size={16} />
      </button>

      {/* Full Screen Search Overlay */}
      <div className={`fixed inset-0 z-[100] transition-all duration-700 ${isOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}>
        <div className="absolute inset-0 bg-white/95 backdrop-blur-2xl" />
        
        <button 
          onClick={() => setIsOpen(false)}
          className="absolute top-12 right-12 text-ink hover:text-brand-fresa transition-colors z-20"
          aria-label="Cerrar buscador"
        >
          <FaTimes size={32} />
        </button>

        <div className="container mx-auto px-6 h-full flex flex-col justify-center relative z-10">
          <span className="text-editorial text-brand-fresa mb-8 block text-center animate-fade-up">Buscador Editorial</span>
          
          <form onSubmit={handleSubmit} className="max-w-4xl mx-auto w-full animate-fade-up" style={{ animationDelay: '0.2s' }}>
            <div className="relative">
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="¿Qué receta buscas hoy?..."
                className="w-full bg-transparent border-b-2 border-brand-fresa/10 py-8 text-4xl md:text-6xl font-serif text-ink outline-none focus:border-brand-fresa transition-all placeholder:text-gray-200 placeholder:italic"
              />
              <button 
                type="submit"
                className="absolute right-0 bottom-8 text-brand-fresa hover:text-brand-red transition-colors"
                aria-label="Buscar"
              >
                <FaSearch size={32} />
              </button>
            </div>
            
            <div className="mt-12 flex flex-wrap justify-center gap-4">
              <span className="text-sm font-bold uppercase tracking-[0.3em] text-gray-600 w-full text-center mb-4">Sugerencias Gourmet</span>
              {['Paella', 'Tapas', 'Chocolate', 'Crema Catalana', 'Gazpacho'].map((tag) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => setQuery(tag)}
                  className="px-6 py-2 bg-brand-fresa/5 text-brand-fresa text-sm font-bold uppercase tracking-widest rounded-full hover:bg-brand-fresa hover:text-white transition-all border border-brand-fresa/10"
                >
                  {tag}
                </button>
              ))}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
