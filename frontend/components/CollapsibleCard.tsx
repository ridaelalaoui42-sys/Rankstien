
'use client';

import { useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { Post } from '@/types';
import { 
  FaChevronDown, 
  FaChevronUp, 
  FaStar, 
  FaShareAlt, 
  FaHeart, 
  FaBookOpen, 
  FaUtensils, 
  FaClock, 
  FaRegBookmark, 
  FaBookmark,
  FaFire,
  FaLeaf,
  FaWineGlass
} from 'react-icons/fa';
import { calculateReadTime } from '@/lib/utils';
import dynamic from 'next/dynamic';

const QuickViewModal = dynamic(() => import('./QuickViewModal'), {
  ssr: false,
});

interface CollapsibleCardProps {
  post: Post;
  index: number;
}

export default function CollapsibleCard({ post, index }: CollapsibleCardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [isFullContentOpen, setIsFullContentOpen] = useState(false);
  const [isLiked, setIsLiked] = useState(false);
  const [isSaved, setIsSaved] = useState(false);
  const [isQuickViewOpen, setIsQuickViewOpen] = useState(false);

  const recipeData = post.recipe_schema;
  const readTime = calculateReadTime(post.content);
  const averageRating = post.rating_value || 4.8;
  const ratingCount = post.rating_count || 12;

  return (
    <div 
      className="flex flex-col group animate-fade-up relative perspective-1000"
      style={{ animationDelay: `${index * 0.1}s` }}
    >
      {/* Premium Badge for Featured Content */}
      {index === 0 && (
        <div className="absolute -top-4 -left-4 z-30 bg-ink text-white px-6 py-2 rounded-full text-sm font-bold uppercase tracking-[0.4em] shadow-2xl flex items-center space-x-2">
          <FaFire className="text-brand-fresa animate-pulse" />
          <span>Destacado de la Semana</span>
        </div>
      )}

      {/* Image Container with High-End Visual Effects */}
      <div className="relative aspect-[4/5] mb-8 overflow-hidden rounded-[3.5rem] bg-cream-dark shadow-[0_30px_60px_rgba(189,30,45,0.08)] group-hover:shadow-[0_50px_100px_rgba(189,30,45,0.15)] transition-all duration-1000 ease-[cubic-bezier(0.23,1,0.32,1)]">
        {post.hero_image && post.hero_image !== 'PLACEHOLDER' ? (
          <Image
            src={post.hero_image}
            alt={`Fotografía editorial de ${post.title} - RecetaDolce`}
            fill
            className="object-cover group-hover:scale-105 transition-all duration-[3000ms] ease-out filter brightness-[0.95] group-hover:brightness-100"
            sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-fresa-gradient opacity-10 font-serif text-9xl select-none">
            RD
          </div>
        )}
        
        {/* Glassmorphic Overlays */}
        <div className="absolute inset-0 bg-gradient-to-t from-ink/80 via-ink/20 to-transparent opacity-40 group-hover:opacity-20 transition-opacity duration-700" />
        
        {/* Interaction Toolbar */}
        <div className="absolute top-4 right-4 md:top-8 md:right-8 flex flex-col space-y-3 md:space-y-4 translate-x-0 md:translate-x-16 md:group-hover:translate-x-0 transition-transform duration-700 cubic-bezier(0.23,1,0.32,1) delay-100">
           <button 
             onClick={(e) => { e.preventDefault(); setIsLiked(!isLiked); }}
             className={`w-9 h-9 md:w-12 md:h-12 rounded-full flex items-center justify-center backdrop-blur-xl border border-white/30 transition-all transform hover:scale-110 active:scale-90 ${
               isLiked ? 'bg-brand-fresa text-white' : 'bg-white/10 text-white hover:bg-white/30'
             }`}
             aria-label={isLiked ? "Quitar de favoritos" : "Añadir a favoritos"}
           >
             <FaHeart size={12} className={isLiked ? 'animate-bounce-small' : ''} />
           </button>
           
           <button 
             onClick={(e) => { e.preventDefault(); setIsSaved(!isSaved); }}
             className={`w-9 h-9 md:w-12 md:h-12 rounded-full flex items-center justify-center backdrop-blur-xl border border-white/30 transition-all transform hover:scale-110 active:scale-90 ${
               isSaved ? 'bg-ink text-white' : 'bg-white/10 text-white hover:bg-white/30'
             }`}
             aria-label={isSaved ? "Quitar del recetario" : "Guardar en recetario"}
           >
             {isSaved ? <FaBookmark size={12} /> : <FaRegBookmark size={12} />}
           </button>

           <button 
             className="w-9 h-9 md:w-12 md:h-12 rounded-full bg-white/10 backdrop-blur-xl border border-white/30 text-white flex items-center justify-center hover:bg-white/30 transition-all transform hover:scale-110"
             aria-label="Compartir esta obra"
           >
             <FaShareAlt size={12} />
           </button>
        </div>

        {/* Dynamic Context Tags */}
        <div className="absolute bottom-4 left-4 right-4 md:bottom-8 md:left-8 md:right-8 flex items-center justify-between z-10">
          <div className="flex items-center space-x-2 md:space-x-3">
            <span className="px-3 py-1.5 md:px-5 md:py-2.5 bg-white/95 backdrop-blur-md rounded-full text-sm md:text-xs font-bold uppercase tracking-[0.4em] text-brand-fresa shadow-2xl border border-brand-fresa/10">
              {post.category}
            </span>
            <div className="px-3 py-1.5 md:px-5 md:py-2.5 bg-ink/90 backdrop-blur-md text-white rounded-full text-[7px] md:text-sm font-bold uppercase tracking-[0.3em] flex items-center space-x-2 md:space-x-3 shadow-2xl">
              <FaClock size={8} className="text-brand-fresa" />
              <span>{readTime} MIN</span>
            </div>
          </div>
          
          <div className="flex items-center space-x-1.5 md:space-x-2 px-3 py-1.5 md:px-5 md:py-2.5 bg-white/95 backdrop-blur-md rounded-full text-ink text-xs md:text-sm font-bold border border-brand-fresa/10 shadow-2xl">
            <FaStar className="text-brand-fresa" />
            <span className="tracking-tighter">{averageRating}</span>
          </div>
        </div>
      </div>

      {/* Content Architecture */}
      <div className="px-4 md:px-6">
        <Link href={`/${post.slug}`} className="block group/title mb-4 md:mb-6">
          <h3 className="text-3xl md:text-5xl font-serif text-ink group-hover/title:text-brand-fresa transition-all duration-700 leading-[1.1] tracking-tight">
            {post.title}
          </h3>
        </Link>
        
        <div className="flex items-center space-x-4 md:space-x-6 mb-6 md:mb-8">
          <div className="h-px w-8 md:w-10 bg-brand-fresa/20 group-hover:w-16 transition-all duration-1000 ease-out" />
          <div className="flex items-center space-x-3 md:space-x-4">
             <span className="text-sm md:text-sm font-bold uppercase tracking-[0.5em] text-gray-600">
               {post.difficulty || 'Editorial'} 
             </span>
             <span className="w-1.5 h-1.5 bg-brand-fresa/10 rounded-full" />
             <span className="text-sm md:text-sm font-bold uppercase tracking-[0.5em] text-gray-600">
               {recipeData?.recipeCuisine || 'Alta Cocina'}
             </span>
          </div>
        </div>
        
        <p className="text-gray-600 line-clamp-2 text-sm md:text-base mb-8 md:mb-12 leading-relaxed font-serif italic opacity-80 group-hover:opacity-100 transition-all duration-700">
          {post.excerpt || post.recipe_schema?.description || 'Una exploración sensorial de los sabores más puros de nuestra tierra.'}
        </p>

        <button 
          onClick={() => setIsQuickViewOpen(true)}
          className="mb-8 text-sm md:text-xs font-bold uppercase tracking-[0.4em] text-brand-fresa flex items-center space-x-3 hover:translate-x-2 transition-transform group/qv"
        >
          <span className="w-6 md:w-8 h-px bg-brand-fresa/30 group-hover/qv:w-12 transition-all" />
          <span>Vista Rápida</span>
        </button>

        {/* Premium Action Grid */}
        <div className="flex flex-col space-y-4 md:space-y-6 pt-6 md:pt-8 border-t border-brand-fresa/10">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between space-y-6 sm:space-y-0">
            <div className="flex flex-wrap gap-2 md:space-x-3 md:gap-0">
              <button 
                onClick={() => { setIsOpen(!isOpen); setShowSummary(false); }}
                className={`group/btn flex items-center space-x-2 md:space-x-4 text-[7px] md:text-sm font-bold transition-all uppercase tracking-[0.2em] md:tracking-[0.4em] px-4 py-2.5 md:px-8 md:py-4 rounded-full ${
                  isOpen ? 'bg-ink text-white shadow-2xl scale-105' : 'bg-cream-base text-brand-fresa hover:bg-brand-fresa/10 border border-brand-fresa/5'
                }`}
              >
                <FaUtensils size={10} className={isOpen ? 'animate-pulse' : 'group-hover/btn:rotate-12 transition-transform'} />
                <span>{isOpen ? 'Cerrar' : 'Pasos'}</span>
              </button>
              
              <button 
                onClick={() => { setShowSummary(!showSummary); setIsOpen(false); setIsFullContentOpen(false); }}
                className={`group/btn flex items-center space-x-2 md:space-x-4 text-[7px] md:text-sm font-bold transition-all uppercase tracking-[0.2em] md:tracking-[0.4em] px-4 py-2.5 md:px-8 md:py-4 rounded-full ${
                  showSummary ? 'bg-brand-fresa text-white shadow-2xl scale-105' : 'bg-white text-gray-600 hover:text-brand-fresa border border-gray-100 hover:border-brand-fresa/20'
                }`}
              >
                <FaBookOpen size={10} />
                <span>Extracto</span>
              </button>

              <button 
                onClick={() => { setIsFullContentOpen(!isFullContentOpen); setIsOpen(false); setShowSummary(false); }}
                className={`group/btn flex items-center space-x-2 md:space-x-4 text-[7px] md:text-sm font-bold transition-all uppercase tracking-[0.2em] md:tracking-[0.4em] px-4 py-2.5 md:px-8 md:py-4 rounded-full ${
                  isFullContentOpen ? 'bg-ink text-white shadow-2xl scale-105' : 'bg-cream-soft text-gray-600 hover:text-ink border border-brand-fresa/5'
                }`}
              >
                <span>{isFullContentOpen ? 'Menos' : 'Lectura'}</span>
              </button>
            </div>

            <Link 
              href={`/${post.slug}`}
              className="group/link flex items-center justify-between sm:justify-end space-x-4 text-xs md:text-sm font-black text-ink uppercase tracking-[0.5em]"
            >
              <div className="flex flex-col items-end">
                <span className="relative">
                   Ver Receta
                   <span className="absolute -bottom-1 left-0 w-full h-[2px] bg-brand-fresa scale-x-0 group-hover/link:scale-x-100 transition-transform duration-700 origin-right group-hover:origin-left" />
                </span>
              </div>
              <div className="w-8 h-8 md:w-10 md:h-10 rounded-full border border-brand-fresa/10 flex items-center justify-center group-hover/link:bg-brand-fresa group-hover/link:text-white transition-all duration-500">
                <span className="group-hover/link:translate-x-1 transition-transform duration-500 text-brand-fresa group-hover/link:text-white">→</span>
              </div>
            </Link>
          </div>
        </div>

        {/* Collapsible Content - Premium Steps Preview */}
        <div className={`grid transition-all duration-700 ease-[cubic-bezier(0.23,1,0.32,1)] ${
          isOpen ? 'grid-rows-[1fr] opacity-100 mt-10' : 'grid-rows-[0fr] opacity-0'
        }`}>
          <div className="overflow-hidden">
             <div className="bg-white/90 backdrop-blur-3xl rounded-[3rem] p-10 border border-brand-fresa/10 shadow-[0_40px_80px_rgba(0,0,0,0.05)] space-y-10 mb-10">
                 <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
                    <div className="space-y-6">
                       <h4 className="flex items-center space-x-3 text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa">
                         <FaLeaf className="text-[12px]" />
                         <span>Ingredientes Clave</span>
                       </h4>
                       <ul className="space-y-4">
                          {(recipeData?.recipeIngredient || recipeData?.ingredients || []).slice(0, 5).map((ing: string, i: number) => (
                             <li key={i} className="text-sm text-gray-600 flex items-center space-x-4 group/ing">
                                <div className="w-1.5 h-1.5 bg-brand-fresa/20 rounded-full group-hover/ing:bg-brand-fresa transition-colors" />
                                <span className="font-serif italic text-gray-600 group-hover:text-ink transition-colors">{ing}</span>
                             </li>
                          ))}
                       </ul>
                    </div>
                    <div className="space-y-6">
                       <h4 className="flex items-center space-x-3 text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa">
                         <FaUtensils className="text-[12px]" />
                         <span>Técnica Editorial</span>
                       </h4>
                       <div className="space-y-4">
                          {(recipeData?.recipeInstructions || recipeData?.instructions || []).slice(0, 2).map((step: any, i: number) => (
                             <div key={i} className="p-6 bg-cream-base/30 rounded-3xl border border-brand-fresa/5 hover:border-brand-fresa/20 transition-all">
                                <p className="text-[13px] text-gray-600 font-serif leading-relaxed line-clamp-3 italic">
                                  {typeof step === 'string' ? step : step.text}
                                </p>
                             </div>
                          ))}
                       </div>
                    </div>
                 </div>
                 
                 <div className="pt-8 border-t border-brand-fresa/5 flex items-center justify-between text-sm text-gray-600 font-bold uppercase tracking-[0.3em]">
                    <span>Nutrición Estimada: {recipeData?.nutrition?.calories || '320'} kcal</span>
                    <Link href={`/${post.slug}#recipe`} className="text-brand-fresa hover:underline">Ver detalles completos</Link>
                 </div>
             </div>
          </div>
        </div>

        {/* Collapsible Content - Editorial Insight */}
        <div className={`grid transition-all duration-700 ease-[cubic-bezier(0.23,1,0.32,1)] ${
          showSummary ? 'grid-rows-[1fr] opacity-100 mt-10' : 'grid-rows-[0fr] opacity-0'
        }`}>
          <div className="overflow-hidden">
             <div className="bg-brand-fresa/[0.03] backdrop-blur-sm rounded-[3rem] p-10 border border-brand-fresa/10 space-y-8 mb-10 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-32 h-32 bg-brand-fresa/5 rounded-full -mr-16 -mt-16 blur-2xl" />
                <h4 className="flex items-center space-x-3 text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa">
                   <FaWineGlass className="text-[12px]" />
                   <span>Nota de la Autora</span>
                </h4>
                <p className="text-[17px] text-gray-600 font-serif italic leading-[1.8] tracking-tight">
                  "{post.content.replace(/[#*`]/g, '').slice(0, 350)}..."
                </p>
                <div className="flex items-center justify-between pt-6">
                   <div className="flex -space-x-3">
                      {[1,2,3].map(i => (
                        <div key={i} className="w-8 h-8 rounded-full border-2 border-white bg-cream-dark overflow-hidden">
                           <Image src={`https://i.pravatar.cc/100?img=${i+10}`} alt="User" width={32} height={32} />
                        </div>
                      ))}
                      <div className="w-8 h-8 rounded-full border-2 border-white bg-brand-fresa text-white text-sm flex items-center justify-center font-bold">
                        +{ratingCount}
                      </div>
                   </div>
                   <Link 
                     href={`/${post.slug}`}
                     className="px-8 py-3 bg-white border border-brand-fresa/10 rounded-full text-xs font-bold uppercase tracking-[0.3em] text-brand-fresa hover:bg-brand-fresa hover:text-white transition-all shadow-sm"
                   >
                     Continuar Lectura
                   </Link>
                </div>
             </div>
          </div>
        </div>

        {/* Collapsible Content - Full Editorial Text (Lectura) */}
        <div className={`grid transition-all duration-1000 ease-[cubic-bezier(0.23,1,0.32,1)] ${
          isFullContentOpen ? 'grid-rows-[1fr] opacity-100 mt-10' : 'grid-rows-[0fr] opacity-0'
        }`}>
          <div className="overflow-hidden">
             <div className="bg-white rounded-[3.5rem] p-12 border border-brand-fresa/10 shadow-[0_40px_100px_rgba(189,30,45,0.05)] space-y-10 mb-10 relative">
                <div className="prose prose-fresa max-w-none">
                   <div className="flex items-center space-x-4 mb-10">
                      <div className="w-12 h-12 rounded-full bg-brand-fresa/10 flex items-center justify-center text-brand-fresa">
                         <FaBookOpen />
                      </div>
                      <span className="text-sm font-bold uppercase tracking-[0.4em] text-ink">Crónica Gastronómica</span>
                   </div>
                   <div className="text-gray-600 font-serif text-lg leading-[2] first-letter:text-7xl first-letter:font-serif first-letter:text-brand-fresa first-letter:mr-3 first-letter:float-left first-letter:leading-[0.8] first-letter:mt-2">
                     {post.content.replace(/[#*`]/g, '').slice(0, 800)}...
                   </div>
                </div>
                <div className="pt-10 border-t border-brand-fresa/5 flex items-center justify-center">
                   <Link 
                     href={`/${post.slug}`}
                     className="group/cta flex items-center space-x-4 bg-brand-fresa text-white px-12 py-5 rounded-full text-sm font-bold uppercase tracking-[0.4em] hover:bg-brand-red transition-all hover:shadow-2xl hover:shadow-brand-fresa/30"
                   >
                     <span>Descubrir la Historia Completa</span>
                     <span className="group-hover/cta:translate-x-2 transition-transform">→</span>
                   </Link>
                </div>
             </div>
          </div>
        </div>
      </div>
      <QuickViewModal 
        post={post} 
        isOpen={isQuickViewOpen} 
        onClose={() => setIsQuickViewOpen(false)} 
      />
    </div>
  );
}
