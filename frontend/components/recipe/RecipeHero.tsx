
import Image from 'next/image';
import Link from 'next/link';
import Breadcrumbs from '../Breadcrumbs';
import PrintButton from '../PrintButton';

interface RecipeHeroProps {
  title: string;
  category: string;
  prepTime?: string;
  cookTime?: string;
  difficulty?: string;
  readTime?: number;
  author?: string;
  slug: string;
}

const slugify = (text: string) => text.toLowerCase().replace(/ /g, '-').replace(/[^\w-]+/g, '');

export default function RecipeHero({
  title,
  category,
  prepTime,
  cookTime,
  difficulty = 'Editorial',
  readTime = 5,
  author = 'Isabella Dolce',
  slug
}: RecipeHeroProps) {
  return (
    <section className="container mx-auto px-6 pt-12 md:pt-24 pb-12 md:pb-20 text-center animate-fade-up">
      <Breadcrumbs 
        items={[
          { label: category, href: `/categoria/${slugify(category)}` },
          { label: title, href: `/${slug}`, current: true }
        ]} 
      />
      
      <div className="flex items-baseline justify-center space-x-1 mb-8 md:mb-10 mt-12 md:mt-16">
        <span className="text-lg md:text-sm font-sans font-extrabold tracking-tighter text-ink uppercase">
          Receta
        </span>
        <span className="text-lg md:text-sm font-serif italic font-light text-brand-fresa">
          Genial
        </span>
        <div className="h-1 w-1 bg-brand-fresa rounded-full" />
      </div>

      <h1 className="text-4xl sm:text-6xl md:text-7xl lg:text-8xl font-serif text-ink mb-10 md:mb-16 max-w-6xl mx-auto leading-[1.2] md:leading-[1.1] tracking-tightest px-4 md:px-0">
        {title}
      </h1>

      <div className="flex flex-wrap items-center justify-center gap-6 md:gap-10 text-xs md:text-sm font-bold uppercase tracking-[0.4em] text-gray-600 mb-16 md:mb-24">
        <div className="flex items-center space-x-3">
          <span className="w-1.5 h-1.5 bg-brand-fresa/40 rounded-full" />
          <span className="text-ink">{author}</span>
        </div>
        <div className="flex items-center space-x-3">
          <span className="w-1.5 h-1.5 bg-brand-fresa/40 rounded-full" />
          <span>{readTime} Min Lectura</span>
        </div>
        <div className="flex items-center space-x-3">
          <span className="w-1.5 h-1.5 bg-brand-fresa/40 rounded-full" />
          <span>{difficulty}</span>
        </div>
      </div>

      {/* Hero Action Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-center space-y-4 sm:space-y-0 sm:space-x-6 mb-12 md:mb-16">
        <Link 
          href="#recipe-card" 
          className="w-full sm:w-auto px-12 py-5 bg-brand-fresa text-white rounded-full text-sm font-bold uppercase tracking-[0.3em] hover:bg-ink transition-all duration-700 shadow-[0_20px_40px_-10px_rgba(255,77,109,0.3)] text-center group"
        >
          <span className="flex items-center justify-center">
            Ir a la Receta
            <svg className="ml-2 w-3 h-3 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M19 14l-7 7m0 0l-7-7m7 7V3"></path>
            </svg>
          </span>
        </Link>
        <PrintButton />
      </div>
    </section>
  );
}
