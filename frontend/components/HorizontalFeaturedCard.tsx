
'use client';

import SafeImage from './SafeImage';
import Link from 'next/link';
import { Post } from '@/types';
import { FaStar, FaClock, FaUsers } from 'react-icons/fa';

interface HorizontalFeaturedCardProps {
  post: Post;
}

export default function HorizontalFeaturedCard({ post }: HorizontalFeaturedCardProps) {
  const averageRating = post.rating_value || 4.9;
  const ratingCount = post.rating_count || 24;

  const imageUrl = !post.hero_image || post.hero_image === 'PLACEHOLDER' 
    ? 'https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282752/RecetaDolce/mediterranean_ingredients_fallback.jpg' 
    : post.hero_image;

  return (
    <Link href={`/${post.slug}`} className="group block mb-12 overflow-hidden bg-white rounded-3xl border border-cream-dark hover:border-brand-fresa/20 transition-all duration-700 shadow-lg hover:shadow-2xl transform hover:-translate-y-1" aria-label={`Ver receta destacada: ${post.title}`}>
      <div className="flex flex-col lg:flex-row min-h-[350px]">
        {/* Image - 50% width for balance */}
        <div className="w-full lg:w-1/2 relative overflow-hidden bg-cream-soft">
          <SafeImage
            src={imageUrl}
            alt={post.title}
            fill
            className="object-cover transition-transform duration-[3000ms] group-hover:scale-105"
            priority
            sizes="(max-width: 1024px) 100vw, 50vw"
          />
          <div className="absolute top-6 left-6 z-20">
            <span className="px-5 py-2 bg-brand-fresa text-white text-sm font-bold uppercase tracking-[0.4em] shadow-lg rounded-sm">
              Selección de Portada
            </span>
          </div>
          
          {/* Artistic Gradient Overlays */}
          <div className="absolute inset-0 bg-gradient-to-r from-black/20 via-transparent to-transparent opacity-30" />
          <div className="absolute inset-0 bg-brand-fresa/5 opacity-0 group-hover:opacity-100 transition-opacity duration-1000" />
        </div>

        {/* Content - 50% width */}
        <div className="w-full lg:w-1/2 p-8 md:p-12 flex flex-col justify-center relative bg-white">
          {/* Corner flourish */}
          <div className="absolute top-0 right-0 w-24 h-24 bg-cream-base/30 rounded-bl-[4rem] -z-10" />
          
          <div className="flex items-center space-x-4 mb-6">
            <div className="flex text-gold-accent gap-1">
              {[1, 2, 3, 4, 5].map((i) => (
                <FaStar key={i} size={12} className="fill-current" />
              ))}
            </div>
            <span className="w-6 h-px bg-cream-dark" />
            <span className="text-gray-600 text-sm font-bold uppercase tracking-[0.3em]">
              {(post.rating_value || 4.9).toFixed(1)} / 5.0
            </span>
          </div>

          <h2 className="text-3xl md:text-4xl font-serif text-ink mb-5 leading-tight tracking-tight group-hover:text-brand-fresa transition-colors duration-500">
            {post.title}
          </h2>

          <div className="w-12 h-1 bg-brand-fresa/20 mb-6" />

          <p className="text-gray-600 font-serif italic text-lg mb-8 line-clamp-3 leading-relaxed">
            {post.excerpt || 'Una técnica refinada y sabores que cuentan historias. Descubre los secretos de esta preparación magistral que hoy protagoniza nuestra cocina.'}
          </p>

          <div className="flex flex-wrap items-center gap-8 border-t border-cream-dark/50 pt-8 mt-auto">
            <div className="flex items-center gap-3 text-ink/70">
              <FaUsers size={16} className="text-brand-fresa/50" />
              <span className="text-sm font-bold uppercase tracking-[0.3em]">{post.recipe_schema?.recipeYield || '4'} Raciones</span>
            </div>
            <div className="flex items-center gap-3 text-ink/70">
              <FaClock size={16} className="text-brand-fresa/50" />
              <span className="text-sm font-bold uppercase tracking-[0.3em]">{post.prep_time || 45} Minutos</span>
            </div>
          </div>
          
          <div className="mt-10">
            <span className="text-brand-fresa text-sm font-bold uppercase tracking-[0.4em] group-hover:tracking-[0.6em] transition-all duration-500">
              Ver el reportaje completo →
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
