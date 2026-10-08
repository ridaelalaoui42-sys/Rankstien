

import SafeImage from './SafeImage';
import { getPostImageUrl } from '@/lib/imageHelper';
import Link from 'next/link';
import { Post } from '@/types';
import { FaClock } from 'react-icons/fa';

interface StandardRecipeCardProps {
  post: Post;
}

export default function StandardRecipeCard({ post }: StandardRecipeCardProps) {
  const imageUrl = getPostImageUrl(post);

  return (
    <Link href={`/${post.slug}`} className="group block h-full" aria-label={`Ver receta de ${post.title}`}>
      <div className="relative h-full flex flex-col bg-white rounded-2xl overflow-hidden border border-cream-dark/30 hover:border-brand-fresa/20 transition-all duration-700 hover:shadow-xl transform hover:-translate-y-1">
        {/* Image Container - Professional Aspect Ratio */}
        <div className="relative aspect-[4/3] overflow-hidden">
          <SafeImage
            src={imageUrl}
            alt={post.title}
            fill
            className="object-cover transition-transform duration-[2000ms] group-hover:scale-105"
            sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
          />
          
          {/* Elegant Dark Overlay on Hover */}
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/5 transition-colors duration-700" />
          
          {/* Category Badge - Floating Glassmorphism */}
          <div className="absolute top-4 left-4 z-20">
            <span className="px-3 py-1 bg-white/90 backdrop-blur-md rounded-full text-xs font-bold uppercase tracking-[0.2em] text-brand-fresa shadow-sm border border-white">
              {post.category || 'Receta'}
            </span>
          </div>
        </div>

        {/* Content Area - Compact Padding */}
        <div className="p-5 flex flex-col flex-1 relative bg-white">
          <div className="mb-3">
            <h3 className="text-ink font-serif text-lg leading-tight group-hover:text-brand-fresa transition-colors duration-500 line-clamp-2">
              {post.title}
            </h3>
          </div>

          <div className="flex-1">
            <p className="text-gray-600 text-sm font-serif italic leading-relaxed line-clamp-2 mb-4">
              {post.excerpt || 'Una técnica impecable y sabores que transportan al corazón de la cocina española.'}
            </p>
          </div>

          <div className="pt-4 border-t border-cream-dark/30 flex justify-between items-center text-xs font-bold uppercase tracking-[0.1em] text-gray-600">
            <div className="flex items-center gap-2">
              <FaClock size={12} className="text-brand-fresa/40" />
              <span>{post.prep_time || 30} MIN</span>
            </div>
            <div className="text-brand-fresa flex items-center gap-2 group-hover:gap-3 transition-all duration-500">
              EXPLORAR <span className="text-base leading-none">→</span>
            </div>
          </div>
        </div>
      </div>
    </Link>
  );
}
