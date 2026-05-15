
'use client';

import { useState, useEffect } from 'react';
import { FaStar, FaRegStar, FaStarHalfAlt, FaPaperPlane, FaQuoteLeft } from 'react-icons/fa';
import { supabase } from '@/lib/supabase';
import { Review } from '@/types';
import DeterministicDate from './DeterministicDate';

interface ReviewSystemProps {
  postId: string;
}

export default function ReviewSystem({ postId }: ReviewSystemProps) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [name, setName] = useState('');
  const [content, setContent] = useState('');
  const [rating, setRating] = useState(5);
  const [hover, setHover] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [hasReviewed, setHasReviewed] = useState(false);

  useEffect(() => {
    fetchReviews();
    const reviewed = localStorage.getItem(`reviewed_${postId}`);
    if (reviewed) setHasReviewed(true);
  }, [postId]);

  async function fetchReviews() {
    setIsLoading(true);
    try {
      const { data, error } = await supabase
        .from('reviews')
        .select('*')
        .eq('post_id', postId)
        .eq('status', 'approved')
        .order('created_at', { ascending: false });

      if (error) throw error;
      setReviews(data || []);
    } catch (err) {
      console.error('Error fetching reviews:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name || !content || isSubmitting || hasReviewed) return;

    setIsSubmitting(true);
    try {
      const { error } = await supabase
        .from('reviews')
        .insert([
          {
            post_id: postId,
            author_name: name,
            content: content,
            rating: rating,
            status: 'approved' // Automatically approved for demo purposes
          },
        ]);

      if (error) throw error;

      // Update post aggregate rating
      await supabase.rpc('increment_rating', { 
        p_post_id: postId, 
        p_new_rating: rating 
      });

      setName('');
      setContent('');
      setHasReviewed(true);
      localStorage.setItem(`reviewed_${postId}`, 'true');
      await fetchReviews();
    } catch (err) {
      console.error('Error posting review:', err);
      alert('Hubo un error al publicar tu reseña.');
    } finally {
      setIsSubmitting(false);
    }
  }

  const renderStars = (currentRating: number, setRatingFn?: (val: number) => void) => {
    const stars = [];
    for (let i = 1; i <= 5; i++) {
      stars.push(
        <button
          key={i}
          type="button"
          disabled={!setRatingFn || hasReviewed}
          onMouseEnter={() => setRatingFn && setHover(i)}
          onMouseLeave={() => setRatingFn && setHover(0)}
          onClick={() => setRatingFn && setRatingFn(i)}
          className={`transition-all duration-300 ${setRatingFn && !hasReviewed ? 'hover:scale-125 cursor-pointer' : 'cursor-default'} ${i <= (hover || currentRating) ? 'text-brand-fresa' : 'text-brand-fresa/20'}`}
          aria-label={setRatingFn ? `Calificar con ${i} estrellas` : undefined}
        >
          {i <= (hover || currentRating) ? <FaStar size={setRatingFn ? 24 : 12} /> : <FaRegStar size={setRatingFn ? 24 : 12} />}
        </button>
      );
    }
    return stars;
  };

  return (
    <div className="space-y-12">
      {/* Review Form */}
      <div className="bg-white rounded-[2rem] p-6 md:p-10 shadow-[0_20px_40px_rgba(189,30,45,0.05)] border border-brand-fresa/5 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-64 h-64 bg-brand-fresa/[0.02] rounded-full -mr-32 -mt-32 blur-3xl" />
        
        <div className="max-w-2xl mx-auto relative z-10">
          <div className="text-center mb-10">
            <h3 className="text-2xl md:text-3xl font-serif text-ink italic mb-2">¿Te ha gustado el resultado?</h3>
            <p className="text-xs text-gray-600 font-bold uppercase tracking-[0.3em]">Comparte tu experiencia con la comunidad</p>
          </div>

          {hasReviewed ? (
            <div className="text-center py-10">
               <div className="w-16 h-16 bg-brand-fresa/10 rounded-full flex items-center justify-center text-brand-fresa mx-auto mb-6">
                 <FaStar size={24} />
               </div>
               <h4 className="text-2xl font-serif text-ink italic mb-2">¡Gracias por tu reseña!</h4>
               <p className="text-sm text-gray-600">Tu opinión ayuda a mantener la excelencia de nuestra cocina.</p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-10">
              <div className="flex flex-col items-center space-y-4 mb-10">
                <span className="text-sm font-bold uppercase tracking-widest text-gray-600">Tu Valoración</span>
                <div className="flex space-x-3">
                  {renderStars(rating, setRating)}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-8">
                <div className="space-y-2">
                  <label className="text-sm uppercase tracking-widest text-gray-600 font-bold ml-1">Nombre de Gourmet</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Ej. Pablo D."
                    required
                    className="w-full bg-cream-base/30 border border-brand-fresa/10 rounded-xl px-5 py-4 text-sm focus:border-brand-fresa outline-none transition-all placeholder:text-gray-300 font-serif"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm uppercase tracking-widest text-gray-600 font-bold ml-1">Tu Reseña Editorial</label>
                  <textarea
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder="Describe los matices, la textura o cualquier consejo de autor..."
                    required
                    rows={4}
                    className="w-full bg-cream-base/30 border border-brand-fresa/10 rounded-xl px-5 py-4 text-sm focus:border-brand-fresa outline-none transition-all placeholder:text-gray-300 font-serif resize-none leading-relaxed"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full bg-brand-fresa text-white py-4 rounded-full font-bold uppercase tracking-[0.3em] text-sm hover:bg-ink transition-all duration-300 shadow-xl shadow-brand-fresa/10 flex items-center justify-center space-x-4 disabled:opacity-50"
              >
                <span>{isSubmitting ? 'Enviando Crítica...' : 'Publicar Reseña'}</span>
                {!isSubmitting && <FaPaperPlane size={10} />}
              </button>
            </form>
          )}
        </div>
      </div>

      {/* Reviews List */}
      <div className="space-y-16">
        <div className="flex items-center justify-between mb-12">
          <h4 className="text-3xl font-serif text-ink italic">Reseñas de la Comunidad</h4>
          <div className="h-px flex-1 mx-10 bg-brand-fresa/10" />
          <span className="text-sm font-bold uppercase tracking-widest text-brand-fresa/40">{reviews.length} Entradas</span>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-20">
            <div className="w-10 h-10 border-4 border-brand-fresa/10 border-t-brand-fresa rounded-full animate-spin" />
          </div>
        ) : reviews.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
            {reviews.map((review) => (
              <div key={review.id} className="bg-white p-8 rounded-3xl border border-brand-fresa/5 shadow-sm hover:shadow-xl transition-all duration-500 animate-fade-up relative">
                <FaQuoteLeft className="absolute top-8 right-8 text-brand-fresa/5" size={40} />
                
                <div className="flex items-center space-x-4 mb-6">
                  <div className="w-12 h-12 bg-cream-base rounded-2xl flex items-center justify-center text-brand-fresa/20 font-serif text-xl">
                    {review.author_name ? review.author_name[0] : '?'}
                  </div>
                  <div>
                    <h5 className="font-serif text-ink font-bold leading-none mb-2">{review.author_name}</h5>
                    <div className="flex items-center space-x-3">
                      <div className="flex">
                        {renderStars(review.rating)}
                      </div>
                      <DeterministicDate 
                        date={review.created_at} 
                        className="text-sm text-gray-600 uppercase tracking-widest"
                        options={{ month: 'short', year: 'numeric' }}
                      />
                    </div>
                  </div>
                </div>
                
                <p className="text-gray-600 leading-relaxed font-serif italic text-sm">
                  "{review.content}"
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-16 bg-cream-base/20 rounded-[4rem] border-2 border-dashed border-brand-fresa/5">
            <p className="text-gray-300 font-serif italic text-2xl">Nuestra comunidad aún no ha dejado su huella en esta receta.</p>
          </div>
        )}
      </div>
    </div>
  );
}
