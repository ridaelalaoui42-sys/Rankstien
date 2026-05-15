
import { Metadata } from 'next';
import Image from 'next/image';
import { supabase } from '@/lib/supabase';
import { Post } from '@/types';
import CollapsibleCard from '@/components/CollapsibleCard';
import Link from 'next/link';
import NewsletterSection from '@/components/NewsletterSection';

import { getSettings } from '@/lib/settings';

export async function generateMetadata(): Promise<Metadata> {
  const settings = await getSettings();
  const siteName = settings?.site_name || 'RecetaDolce';
  
  return {
    title: `Resultados de Búsqueda | ${siteName}`,
    description: 'Explora nuestra colección editorial de recetas basadas en tu búsqueda.',
    alternates: {
      canonical: 'https://RecetaDolce.com/search',
    },
  };
}

async function searchPosts(query: string) {
  const { data: posts } = await supabase
    .from('posts')
    .select('*')
    .or(`title.ilike.%${query}%,content.ilike.%${query}%,excerpt.ilike.%${query}%`)
    .eq('status', 'published')
    .order('created_at', { ascending: false })
    .limit(50);
  
  return (posts as Post[]) || [];
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const query = q || '';
  const posts = query ? await searchPosts(query) : [];

  return (
    <main className="min-h-screen bg-cream-base pb-32">
      {/* Search Header */}
      <section className="relative pt-48 pb-32 text-center overflow-hidden">
        {/* Artistic background elements */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1200px] h-[600px] bg-brand-fresa/5 rounded-full blur-[150px] -z-10" />
        <div className="absolute top-0 left-0 w-full h-full bg-[url('/images/noise.png')] opacity-[0.03] pointer-events-none" />
        
        <div className="container mx-auto px-6">
          <div className="inline-block px-6 py-2 border border-brand-fresa/20 rounded-full text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa mb-10 animate-fade-up">
            Archivo Editorial
          </div>
          
          <h1 className="text-6xl md:text-8xl font-serif text-ink mb-10 italic animate-fade-up" style={{ animationDelay: '0.1s' }}>
            Resultados para <span className="text-brand-fresa">"{query}"</span>
          </h1>
          
          <div className="w-24 h-px bg-brand-fresa/20 mx-auto mb-10 animate-fade-up" style={{ animationDelay: '0.2s' }} />
          
          <p className="max-w-2xl mx-auto text-gray-600 font-serif italic text-xl animate-fade-up leading-relaxed" style={{ animationDelay: '0.3s' }}>
            Hemos seleccionado {posts.length} {posts.length === 1 ? 'tesoro culinario' : 'tesoros culinarios'} que coinciden con tu paladar.
          </p>
        </div>
      </section>

      <section className="container mx-auto px-6 py-20">
        {posts.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-16 gap-y-32">
            {posts.map((post, i) => (
              <div key={post.id} className="animate-fade-up" style={{ animationDelay: `${i * 0.1}s` }}>
                <CollapsibleCard post={post} index={i} />
              </div>
            ))}
          </div>
        ) : (
          <div className="max-w-3xl mx-auto text-center py-40 bg-white rounded-[4rem] shadow-[0_50px_100px_rgba(0,0,0,0.05)] border border-cream-dark/30 p-20 animate-fade-up">
            <div className="relative w-40 h-40 mx-auto mb-12 opacity-30 grayscale contrast-125">
              <Image src="/images/brand/logo.png" alt="logo" fill className="object-contain" sizes="160px" />
            </div>
            <h2 className="text-4xl font-serif text-ink mb-8 italic">No encontramos coincidencias</h2>
            <p className="text-gray-600 italic font-serif text-xl leading-relaxed mb-16 max-w-xl mx-auto">
              Incluso en las mejores cocinas a veces falta un ingrediente. Prueba con términos como "chocolate", "tapas" o "tradicional".
            </p>
            <Link 
              href="/" 
              className="inline-block px-16 py-7 bg-brand-fresa text-white text-sm font-bold uppercase tracking-[0.4em] rounded-full hover:bg-brand-fresa-deep transition-all shadow-[0_20px_40px_rgba(164,19,60,0.2)] hover:shadow-2xl hover:-translate-y-1 duration-500"
            >
              Explorar la Cocina
            </Link>
          </div>
        )}
      </section>
      <NewsletterSection />
    </main>
  );
}
