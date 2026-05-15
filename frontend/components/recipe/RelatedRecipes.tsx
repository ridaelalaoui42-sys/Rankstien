'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import SafeImage from '../SafeImage';
import { Post } from '@/types';

interface RelatedRecipesProps {
  currentSlug: string;
}

const FALLBACK_IMAGE = 'https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282752/RecetaDolce/mediterranean_ingredients_fallback.jpg';

export default function RelatedRecipes({ currentSlug }: RelatedRecipesProps) {
  const [recipes, setRecipes] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchRelated = async () => {
      try {
        const res = await fetch(`/api/posts/related/${currentSlug}`);
        if (!res.ok) throw new Error('Failed to fetch');
        const data = await res.json();
        if (Array.isArray(data)) setRecipes(data);
      } catch (error) {
        console.error('Failed to fetch related recipes:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchRelated();
  }, [currentSlug]);

  if (loading) {
    return (
      <div className="container mx-auto px-6 py-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 animate-pulse">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-cream-base h-80 rounded-sm" />
          ))}
        </div>
      </div>
    );
  }

  if (recipes.length === 0) return null;

  return (
    <section className="container mx-auto px-8 md:px-12 py-8 md:py-10 max-w-[90rem]">
      {/* Section Header - Compact */}
      <div className="text-center mb-8">
        <span className="text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa mb-2 block">
          Sigue Cocinando
        </span>
        <h2 className="text-2xl md:text-3xl font-serif text-ink italic leading-tight">
          También te gustará
        </h2>
        <div className="w-12 h-px bg-brand-fresa/20 mx-auto mt-4" />
      </div>

      {/* Cards Grid - Density Optimized */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-8 lg:gap-10">
        {recipes.map((recipe) => {
          const imgSrc =
            !recipe.hero_image || recipe.hero_image === 'PLACEHOLDER'
              ? FALLBACK_IMAGE
              : recipe.hero_image;

          return (
            <Link
              key={recipe.id}
              href={`/${recipe.slug}`}
              className="group block"
              aria-label={`Ver receta de ${recipe.title}`}
            >
              {/* Image Container */}
              <div className="relative aspect-[4/3] rounded-[2rem] overflow-hidden bg-cream-base border-8 border-white shadow-xl group-hover:shadow-2xl transition-all duration-700">
                <SafeImage
                  src={imgSrc}
                  alt={recipe.title}
                  fill
                  sizes="(max-width: 768px) 100vw, 33vw"
                  className="object-cover group-hover:scale-105 transition-transform duration-1000"
                />
                <div className="absolute inset-0 bg-ink/5 opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
              </div>

              {/* Content area */}
              <div className="pt-4 px-2">
                <span className="text-xs font-bold uppercase tracking-[0.2em] text-brand-fresa/60 block mb-2">
                  {recipe.category}
                </span>
                <h3 className="text-ink font-serif text-xl leading-snug line-clamp-2 group-hover:text-brand-fresa transition-colors duration-500">
                  {recipe.title}
                </h3>
                
                <div className="mt-4 pt-4 border-t border-cream-dark/30 flex justify-between items-center text-xs font-bold uppercase tracking-widest text-gray-600">
                  <span className="flex items-center gap-2">
                    <span className="w-1 h-1 rounded-full bg-brand-fresa/30" />
                    {recipe.prep_time || 30} MIN
                  </span>
                  <span className="text-brand-fresa flex items-center gap-2 group-hover:gap-3 transition-all duration-500">
                    EXPLORAR <span>→</span>
                  </span>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
