
'use client';

import { Post } from '@/types';
import { FaTimes, FaUtensils, FaClock, FaStar, FaPrint } from 'react-icons/fa';
import Image from 'next/image';
import Link from 'next/link';
import { useEffect, useState } from 'react';

interface QuickViewModalProps {
  post: Post;
  isOpen: boolean;
  onClose: () => void;
}

export default function QuickViewModal({ post, isOpen, onClose }: QuickViewModalProps) {
  const [contentText, setContentText] = useState('');

  useEffect(() => {
    if (isOpen) {
      // Prevent body scroll
      document.body.style.overflow = 'hidden';
      // Clean content for preview - remove markdown symbols
      const cleanContent = (post.content || '')
        .replace(/[#*`_]/g, '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // Remove links keep text
        .slice(0, 450) + '...';
      setContentText(cleanContent);
    } else {
      document.body.style.overflow = 'unset';
    }
  }, [isOpen, post.content]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 md:p-8">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-ink/60 backdrop-blur-sm animate-fade-in" 
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative w-full max-w-6xl max-h-[90vh] bg-white rounded-[3rem] shadow-[0_50px_100px_rgba(0,0,0,0.2)] overflow-hidden animate-zoom-in flex flex-col md:flex-row border border-cream-dark/20">
        {/* Close Button */}
        <button 
          onClick={onClose}
          className="absolute top-8 right-8 z-50 w-12 h-12 bg-white/60 backdrop-blur-xl rounded-full flex items-center justify-center text-ink hover:bg-brand-fresa hover:text-white transition-all duration-500 shadow-xl border border-white/20"
          aria-label="Cerrar vista rápida"
        >
          <FaTimes size={16} />
        </button>

        {/* Left: Image & Stats */}
        <div className="w-full md:w-[45%] h-80 md:h-auto relative bg-cream-soft overflow-hidden">
          {post.hero_image && (
            <Image
              src={post.hero_image}
              alt={post.title}
              fill
              sizes="(max-width: 768px) 100vw, 45vw"
              className="object-cover transition-transform duration-[2000ms] hover:scale-110"
              onError={(e) => {
                const target = e.target as HTMLImageElement;
                target.src = 'https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282752/RecetaDolce/mediterranean_ingredients_fallback.jpg';
              }}
            />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
          
          <div className="absolute bottom-12 left-12 right-12 text-white">
            <span className="inline-block px-5 py-2 bg-brand-fresa rounded-full text-sm font-bold uppercase tracking-[0.3em] mb-6 shadow-xl">
              {post.category || 'Receta Editorial'}
            </span>
            <h2 className="text-4xl md:text-5xl font-serif leading-[1.1] mb-8">{post.title}</h2>
            
            <div className="flex items-center space-x-8 text-sm font-bold uppercase tracking-[0.2em] text-white/90">
              <div className="flex items-center space-x-3">
                <FaClock className="text-brand-fresa-light" size={14} />
                <span>{post.prep_time || 45} MIN</span>
              </div>
              <div className="flex items-center space-x-3">
                <FaStar className="text-gold-accent" size={14} />
                <span>{(post.rating_value || 4.9).toFixed(1)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Content */}
        <div className="w-full md:w-[55%] overflow-y-auto p-12 md:p-24 bg-white custom-scrollbar">
          <div className="max-w-xl mx-auto">
            <div className="flex items-center space-x-6 mb-12">
              <span className="text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa">Vista Rápida</span>
              <div className="h-px flex-1 bg-cream-dark" />
            </div>

            <div className="prose prose-sm md:prose-base prose-stone font-serif italic text-gray-700 leading-relaxed mb-16 max-w-none">
              <p>{contentText}</p>
            </div>

            {/* Quick Actions */}
            <div className="pt-12 border-t border-cream-dark flex flex-col sm:flex-row items-center justify-between gap-8">
              <Link 
                href={`/${post.slug}`}
                onClick={onClose}
                className="w-full sm:w-auto px-12 py-6 bg-brand-fresa text-white rounded-full text-sm font-bold uppercase tracking-[0.3em] hover:bg-brand-fresa-deep hover:shadow-2xl hover:-translate-y-1 transition-all duration-500 text-center"
              >
                Ver Receta Completa
              </Link>
              <button 
                onClick={() => window.print()}
                className="flex items-center space-x-4 text-sm font-bold text-gray-600 uppercase tracking-[0.2em] hover:text-brand-fresa transition-colors group"
                aria-label="Imprimir receta"
              >
                <FaPrint className="group-hover:scale-110 transition-transform" />
                <span>Imprimir Receta</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
