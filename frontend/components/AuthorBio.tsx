
import SafeImage from './SafeImage';
import Link from 'next/link';
import { FaInstagram, FaGlobe, FaCheckCircle, FaAward, FaGraduationCap } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';
import { SITE_IMAGES } from '@/lib/siteImages';

export default function AuthorBio() {
  return (
    <div className="bg-white rounded-[3rem] p-8 md:p-12 border border-brand-fresa/5 shadow-[0_30px_60px_rgba(189,30,45,0.03)] relative overflow-hidden group">
      {/* Decorative background effects */}
      <div className="absolute top-0 right-0 w-64 h-64 bg-brand-fresa/[0.02] rounded-full -mr-32 -mt-32 blur-3xl transition-all duration-1000 group-hover:bg-brand-fresa/5" />
      <div className="absolute bottom-0 left-0 w-48 h-48 bg-brand-fresa/[0.01] rounded-full -ml-24 -mb-24 blur-2xl" />
      
      <div className="flex flex-col md:flex-row items-center md:items-start gap-8 md:gap-12 relative z-10">
        {/* Author Image with Status Badges */}
        <div className="relative">
          <div className="relative w-40 h-40 rounded-full overflow-hidden border-8 border-cream-soft shadow-2xl">
            <SafeImage
              src={SITE_IMAGES.author}
              alt="Isabella Dolce - Chef Editora de RecetaDolce"
              fill
              sizes="160px"
              className="object-cover group-hover:scale-105 transition-transform duration-[2000ms]"
            />
          </div>
          {/* Verified Badge Overlay */}
          <div className="absolute -bottom-2 right-4 bg-white p-2 rounded-full shadow-lg border border-brand-fresa/10 translate-y-2 group-hover:translate-y-0 transition-transform duration-700">
            <FaCheckCircle className="text-brand-fresa" size={20} aria-hidden="true" />
          </div>
        </div>

        <div className="text-center md:text-left flex-grow">
          {/* Header & Badges */}
          <div className="flex flex-wrap items-center justify-center md:justify-start gap-3 mb-4">
            <span className="text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa">Directora Editorial</span>
            <div className="h-4 w-px bg-brand-fresa/10 hidden md:block" />
            <div className="flex items-center space-x-2 px-3 py-1 bg-ink text-white rounded-md">
              <FaGraduationCap size={10} className="text-brand-fresa" aria-hidden="true" />
              <span className="text-sm font-bold uppercase tracking-widest">Le Cordon Bleu</span>
            </div>
            <div className="flex items-center space-x-2 px-3 py-1 bg-cream-dark text-ink rounded-md border border-brand-fresa/10">
              <FaAward size={10} className="text-brand-fresa" aria-hidden="true" />
              <span className="text-sm font-bold uppercase tracking-widest">+15 Años Exp.</span>
            </div>
          </div>

          <h3 className="text-4xl font-serif text-ink mb-6 italic tracking-tight">Isabella Dolce</h3>
          
          <p className="text-gray-600 font-serif italic leading-relaxed mb-10 text-xl max-w-2xl">
            "Mi misión es democratizar la alta cocina española. Creo que la excelencia culinaria no debería ser un secreto, sino una experiencia compartida que eleva el día a día."
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-10 border-y border-brand-fresa/5 py-8">
            <div className="flex items-start space-x-4">
              <div className="w-1 h-1 bg-brand-fresa rounded-full mt-2" />
              <p className="text-sm text-gray-600 font-sans">Especialista en técnicas de repostería y <strong>seguridad alimentaria (Normativa AESAN)</strong>.</p>
            </div>
            <div className="flex items-start space-x-4">
              <div className="w-1 h-1 bg-brand-fresa rounded-full mt-2" />
              <p className="text-sm text-gray-600 font-sans">Divulgadora gastronómica comprometida con la <strong>Ley 17/2011 del BOE</strong>.</p>
            </div>
          </div>
          
          <div className="flex items-center justify-center md:justify-start space-x-8">
            <a href="https://instagram.com/RecetaDolce" target="_blank" rel="noopener noreferrer" className="flex items-center space-x-2 text-gray-600 hover:text-brand-fresa transition-all duration-300 group/social" aria-label="Seguir a Isabella en Instagram">
              <FaInstagram size={18} className="group-hover/social:scale-110 transition-transform" aria-hidden="true" />
              <span className="text-xs font-bold uppercase tracking-[0.2em] opacity-0 group-hover/social:opacity-100 transition-opacity">Instagram</span>
            </a>
            <a href="https://twitter.com/RecetaDolce" target="_blank" rel="noopener noreferrer" className="flex items-center space-x-2 text-gray-600 hover:text-brand-fresa transition-all duration-300 group/social" aria-label="Seguir a Isabella en X">
              <FaXTwitter size={18} className="group-hover/social:scale-110 transition-transform" aria-hidden="true" />
              <span className="text-xs font-bold uppercase tracking-[0.2em] opacity-0 group-hover/social:opacity-100 transition-opacity">X</span>
            </a>
            <Link href="/contact" className="flex items-center space-x-2 text-gray-600 hover:text-brand-fresa transition-all duration-300 group/social" aria-label="Contactar con Isabella">
              <FaGlobe size={18} className="group-hover/social:scale-110 transition-transform" aria-hidden="true" />
              <span className="text-xs font-bold uppercase tracking-[0.2em] opacity-0 group-hover/social:opacity-100 transition-opacity">Contacto</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
