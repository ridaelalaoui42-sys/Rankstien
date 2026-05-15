
import Link from 'next/link';
import { FaHome, FaSearch, FaUtensils } from 'react-icons/fa';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-cream-base flex items-center justify-center px-6 py-24">
      <div className="max-w-3xl w-full text-center animate-fade-up">
        {/* Decorative Element */}
        <div className="mb-12 flex justify-center">
          <div className="relative">
            <div className="text-[12rem] font-serif text-brand-fresa/5 leading-none select-none">404</div>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-8xl transform -rotate-12">🍓</span>
            </div>
          </div>
        </div>

        <h1 className="text-5xl md:text-6xl font-serif text-ink mb-6 leading-tight">
          Página no encontrada
        </h1>
        
        <p className="text-xl text-gray-600 font-serif italic mb-12 max-w-xl mx-auto leading-relaxed">
          Parece que esta receta se ha esfumado de nuestra cocina. No te preocupes, 
          siempre hay algo delicioso esperando a ser descubierto.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-6">
          <Link 
            href="/" 
            className="w-full sm:w-auto flex items-center justify-center space-x-3 px-10 py-5 bg-brand-fresa text-white rounded-full font-bold uppercase tracking-widest text-sm hover:bg-brand-red transition-all duration-500 shadow-xl shadow-brand-fresa/20 group"
          >
            <FaHome className="group-hover:-translate-y-0.5 transition-transform" />
            <span>Volver al Inicio</span>
          </Link>
          
          <Link 
            href="/search" 
            className="w-full sm:w-auto flex items-center justify-center space-x-3 px-10 py-5 bg-white text-ink border border-brand-fresa/10 rounded-full font-bold uppercase tracking-widest text-sm hover:bg-cream-dark transition-all duration-500 group"
          >
            <FaSearch className="group-hover:scale-110 transition-transform" />
            <span>Buscar Recetas</span>
          </Link>
        </div>

        {/* Suggestion Section */}
        <div className="mt-24 pt-12 border-t border-brand-fresa/5">
          <div className="flex items-center justify-center space-x-3 mb-8">
            <FaUtensils className="text-brand-fresa/20" />
            <h2 className="text-sm font-bold uppercase tracking-[0.4em] text-gray-600">¿Qué tal algo dulce?</h2>
          </div>
          
          <div className="flex flex-wrap justify-center gap-4 text-sm font-serif italic text-brand-fresa/60">
            <Link href="/categoria/postres" className="hover:text-brand-fresa transition-colors underline decoration-brand-fresa/10 underline-offset-8">Postres</Link>
            <span className="text-gray-300">•</span>
            <Link href="/categoria/arroces" className="hover:text-brand-fresa transition-colors underline decoration-brand-fresa/10 underline-offset-8">Arroces</Link>
            <span className="text-gray-300">•</span>
            <Link href="/categoria/carnes" className="hover:text-brand-fresa transition-colors underline decoration-brand-fresa/10 underline-offset-8">Carnes</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
