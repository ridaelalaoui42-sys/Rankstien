
'use client';

import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabase';
import { FaUserCircle, FaPaperPlane } from 'react-icons/fa';

interface Comment {
  id: string;
  created_at: string;
  author_name: string;
  content: string;
}

interface CommentsProps {
  postId: string;
}

export default function Comments({ postId }: CommentsProps) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [name, setName] = useState('');
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchComments();
  }, [postId]);

  async function fetchComments() {
    setIsLoading(true);
    try {
      const { data, error } = await supabase
        .from('comments')
        .select('*')
        .eq('post_id', postId)
        .order('created_at', { ascending: false });

      if (error) throw error;
      setComments(data || []);
    } catch (err) {
      console.error('Error fetching comments:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name || !content || isSubmitting) return;

    setIsSubmitting(true);
    try {
      const { error } = await supabase
        .from('comments')
        .insert([
          {
            post_id: postId,
            author_name: name,
            content: content,
          },
        ]);

      if (error) throw error;

      setName('');
      setContent('');
      await fetchComments();
    } catch (err) {
      console.error('Error posting comment:', err);
      alert('Hubo un error al publicar tu comentario.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="space-y-12">
      {/* Comment Form */}
      <div className="bg-white/50 backdrop-blur-md rounded-[2.5rem] p-8 md:p-12 border border-brand-fresa/5 shadow-sm">
        <h4 className="text-xl font-serif text-ink mb-8 italic">Comparte tu experiencia</h4>
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="text-sm uppercase tracking-widest text-gray-600 font-bold ml-1">Nombre</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ej. Isabella D."
                required
                className="w-full bg-cream-base/50 border border-brand-fresa/10 rounded-2xl px-6 py-4 text-sm focus:border-brand-fresa outline-none transition-all placeholder:text-gray-300 font-serif"
              />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm uppercase tracking-widest text-gray-600 font-bold ml-1">Tu Comentario</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="¿Qué te pareció la receta? ¿Algún truco especial?"
              required
              rows={4}
              className="w-full bg-cream-base/50 border border-brand-fresa/10 rounded-3xl px-6 py-4 text-sm focus:border-brand-fresa outline-none transition-all placeholder:text-gray-300 font-serif resize-none"
            />
          </div>
          <button
            type="submit"
            disabled={isSubmitting}
            className="bg-brand-fresa text-white px-10 py-4 rounded-full font-bold uppercase tracking-widest text-sm hover:bg-brand-fresa/90 transition-all shadow-lg shadow-brand-fresa/10 flex items-center space-x-3 disabled:opacity-50"
          >
            <span>{isSubmitting ? 'Enviando...' : 'Publicar Comentario'}</span>
            {!isSubmitting && <FaPaperPlane size={10} />}
          </button>
        </form>
      </div>

      {/* Comments List */}
      <div className="space-y-8">
        {isLoading ? (
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 border-4 border-brand-fresa/20 border-t-brand-fresa rounded-full animate-spin" />
          </div>
        ) : comments.length > 0 ? (
          comments.map((comment) => (
            <div key={comment.id} className="flex space-x-6 animate-fade-up">
              <div className="flex-shrink-0">
                <div className="w-12 h-12 bg-brand-fresa/5 rounded-2xl flex items-center justify-center text-brand-fresa/30">
                  <FaUserCircle size={32} />
                </div>
              </div>
              <div className="flex-grow">
                <div className="flex items-center justify-between mb-2">
                  <h5 className="font-serif text-ink font-bold italic">{comment.author_name}</h5>
                  <span className="text-sm text-gray-300 uppercase tracking-widest">
                    {new Date(comment.created_at).toLocaleDateString('es-ES', { month: 'long', day: 'numeric' })}
                  </span>
                </div>
                <p className="text-gray-600 leading-relaxed font-sans italic bg-cream-base/30 rounded-3xl p-6 border border-brand-fresa/5">
                  {comment.content}
                </p>
              </div>
            </div>
          ))
        ) : (
          <div className="text-center py-20 bg-cream-base/20 rounded-[3rem] border border-dashed border-brand-fresa/10">
            <p className="text-gray-600 font-serif italic text-lg">Sé el primero en compartir tu opinión sobre esta delicia.</p>
          </div>
        )}
      </div>
    </div>
  );
}
