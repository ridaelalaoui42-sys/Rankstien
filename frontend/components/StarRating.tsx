
'use client';

import { useState, useEffect } from 'react';
import { FaStar, FaRegStar, FaStarHalfAlt } from 'react-icons/fa';
import { supabase } from '@/lib/supabase';

interface StarRatingProps {
  postId: string;
  initialRating?: number;
  initialCount?: number;
}

export default function StarRating({ postId, initialRating = 4.9, initialCount = 24 }: StarRatingProps) {
  const [rating, setRating] = useState(initialRating);
  const [count, setCount] = useState(initialCount);
  const [hover, setHover] = useState(0);
  const [userRating, setUserRating] = useState(0);
  const [hasRated, setHasRated] = useState(false);

  useEffect(() => {
    const rated = localStorage.getItem(`rated_${postId}`);
    if (rated) {
      setHasRated(true);
      setUserRating(Number(rated));
    }
  }, [postId]);

  const handleRate = async (value: number) => {
    if (hasRated) return;

    setUserRating(value);
    setHasRated(true);
    localStorage.setItem(`rated_${postId}`, value.toString());

    const newCount = count + 1;
    const newRating = ((rating * count) + value) / newCount;
    
    setRating(newRating);
    setCount(newCount);

    try {
      const { error } = await supabase.rpc('increment_rating', { 
        p_post_id: postId, 
        p_new_rating: value 
      });
      if (error) console.error('Error sending rating:', error);
    } catch (err) {
      console.error('Failed to rate:', err);
    }
  };

  const renderStars = () => {
    const stars = [];
    const displayRating = hover || userRating || rating;
    
    for (let i = 1; i <= 5; i++) {
      const isFilled = i <= Math.floor(displayRating);
      const isHalf = i === Math.ceil(displayRating) && displayRating % 1 !== 0 && !hover && !userRating;

      stars.push(
        <button
          key={i}
          disabled={hasRated}
          onMouseEnter={() => !hasRated && setHover(i)}
          onMouseLeave={() => !hasRated && setHover(0)}
          onClick={() => handleRate(i)}
          className={`transition-all duration-500 transform ${!hasRated ? 'hover:scale-125' : ''} ${i <= (hover || userRating) ? 'text-brand-fresa' : 'text-brand-fresa/20'}`}
        >
          {isFilled ? <FaStar size={28} /> : isHalf ? <FaStarHalfAlt size={28} className="text-brand-fresa/60" /> : <FaRegStar size={28} />}
        </button>
      );
    }
    return stars;
  };

  return (
    <div className="bg-white/40 backdrop-blur-md rounded-[2.5rem] p-10 border border-brand-fresa/10 flex flex-col items-center text-center max-w-xl mx-auto shadow-sm">
      <span className="text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa/60 mb-6">Valoración de la Crítica</span>
      
      <div className="flex items-center space-x-3 mb-8">
        {renderStars()}
      </div>

      <div className="space-y-2">
        <p className="text-3xl font-serif text-ink italic">
          {rating.toFixed(1)} <span className="text-lg text-gray-600 not-italic">/ 5.0</span>
        </p>
        <p className="text-xs text-gray-600 font-sans uppercase tracking-widest">
          {hasRated ? '¡Tu opinión ha sido registrada!' : `Basado en ${count} experiencias culinarias`}
        </p>
      </div>

      {!hasRated && (
        <div className="mt-8 pt-8 border-t border-brand-fresa/5 w-full">
           <p className="text-sm font-bold uppercase tracking-widest text-brand-fresa/40">Tu voto ayuda a nuestra comunidad</p>
        </div>
      )}
    </div>
  );
}
