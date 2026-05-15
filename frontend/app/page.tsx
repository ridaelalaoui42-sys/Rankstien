
import SafeImage from '@/components/SafeImage';
import Image from 'next/image';
import Link from 'next/link';
import { Metadata } from 'next';
import { supabase } from '@/lib/supabase';
import { Post } from '@/types';

import HorizontalFeaturedCard from '@/components/HorizontalFeaturedCard';
import SocialStats from '@/components/SocialStats';
import CuisineGrid from '@/components/CuisineGrid';
import StandardRecipeCard from '@/components/StandardRecipeCard';
import NewsletterSection from '@/components/NewsletterSection';
import AuthorBio from '@/components/AuthorBio';
import RecipeGrid from '@/components/RecipeGrid';
import AdUnit from '@/components/AdUnit';
import EEATSignals from '@/components/EEATSignals';
import { getSettings } from '@/lib/settings';
import { SITE_IMAGES } from '@/lib/siteImages';

export const revalidate = 3600;

export const metadata: Metadata = {
  title: 'RecetaDolce | Alta Cocina Española y Recetas Infalibles',
  description: 'Descubre recetas probadas con pasión editorial. Desde clásicos españoles hasta repostería fina, Isabella Dolce te guía paso a paso.',
  alternates: {
    canonical: 'https://RecetaDolce.com',
  },
};

async function getPosts() {
  try {

    const { data: posts, error } = await supabase
      .from('posts')
      .select('*')
      .eq('is_published', true)
      .order('published_at', { ascending: false })
      .limit(30);
    
    if (error) {
      console.error('Supabase fetch error:', error.message);
      return [];
    }

    return (posts as Post[]) || [];
  } catch (err: any) {
    console.error('getPosts crash:', err.message);
    return [];
  }
}

export default async function Home() {
  const allPosts = await getPosts();
  const settings = await getSettings();
  const featuredPost = allPosts[0];
  const recentPosts = allPosts.slice(1); // Get all remaining posts for the toggle

  return (
    <main className="min-h-screen bg-cream-base">
      {/* RecipeTin Eats Style Hero - Personal & Inviting */}
      <section className="relative pt-6 pb-12 md:pt-12 md:pb-20 overflow-hidden bg-white border-b border-cream-dark/30">
        <div className="container mx-auto px-4 md:px-8 max-w-7xl">
          <div className="flex flex-col lg:flex-row items-center gap-10 lg:gap-16">
            <div className="w-full lg:w-1/2 space-y-8 text-center lg:text-left animate-fade-up">
              <div className="inline-flex items-center space-x-4 text-brand-fresa">
                <span className="w-12 h-px bg-brand-fresa/30" />
                <span className="text-sm font-bold uppercase tracking-[0.5em]">Bienvenido a mi cocina</span>
              </div>
              <h1 className="text-4xl md:text-5xl lg:text-6xl font-serif text-ink italic leading-[1.05] tracking-tightest">
                Recetas que <br />
                <span className="text-fresa-gradient">Realmente</span> Funcionan.
              </h1>
              <p className="text-lg md:text-xl font-serif text-gray-600 italic leading-relaxed max-w-xl mx-auto lg:mx-0">
                "Soy Isabella, y paso mis días probando recetas para que tú no tengas que hacerlo. Aquí solo encontrarás platos infalibles y deliciosos."
              </p>
              <div className="pt-6 flex flex-col sm:flex-row items-center gap-8 justify-center lg:justify-start">
                <Link 
                  href="#recetas" 
                  className="px-10 py-4 bg-brand-fresa text-white rounded-full text-sm font-bold uppercase tracking-[0.4em] hover:bg-brand-red transition-all shadow-xl shadow-brand-fresa/20 transform hover:-translate-y-1"
                >
                  Explorar Recetas
                </Link>
                <Link 
                  href="/about" 
                  className="text-sm font-bold uppercase tracking-[0.4em] text-ink hover:text-brand-fresa transition-colors border-b-2 border-ink/5 pb-2 hover:border-brand-fresa/30"
                >
                  Mi Historia
                </Link>
              </div>
            </div>
            
            <div className="w-full lg:w-1/2 relative group">
              <div className="relative rounded-[2.5rem] md:rounded-[3rem] overflow-hidden shadow-2xl border-[12px] border-white transform rotate-2 group-hover:rotate-0 transition-transform duration-500 ease-out" style={{ aspectRatio: '4/3' }}>
                <Image 
                  src={SITE_IMAGES.homeHero}
                  alt="Alta Cocina Editorial"
                  fill
                  className="object-cover transition-transform duration-700 group-hover:scale-105"
                  priority
                  fetchPriority="high"
                  sizes="(max-width: 1024px) 100vw, 50vw"
                />
              </div>
              {/* Decorative elements */}
              <div className="absolute -bottom-20 -right-20 w-80 h-80 bg-brand-fresa/10 rounded-full blur-3xl -z-10" />
              <div className="absolute -top-20 -left-20 w-48 h-48 bg-gold-accent/10 rounded-full blur-3xl -z-10" />
            </div>
          </div>
        </div>
      </section>

      {/* Featured Entry Section */}
      <section className="container mx-auto px-4 md:px-8 -mt-16 relative z-30 max-w-7xl">
        {featuredPost && <HorizontalFeaturedCard post={featuredPost} />}
      </section>

      {/* Social Stats - Warm Beige Background */}
      <div className="bg-cream-soft/30 py-12">
        <SocialStats />
      </div>

      {/* Categories Grid - Circular Inspired by RecipeTin Eats */}
      <div className="container mx-auto px-4 md:px-8 max-w-7xl">
        <CuisineGrid />
      </div>

      {/* Ad Placeholder after Hero/Categories */}
      {settings?.ads_top_slot && (
        <div className="container mx-auto px-4 md:px-8 mb-16 max-w-7xl">
          <AdUnit slot={settings.ads_top_slot} label="Sugerencias" />
        </div>
      )}

      {/* Main Content Grid with Sidebar style */}
      <section id="recetas" className="container mx-auto px-4 md:px-8 py-12 md:py-20 max-w-7xl">
        <div className="flex flex-col lg:flex-row gap-12 lg:gap-16">
          
          {/* Recipes Column */}
          <div className="w-full lg:w-2/3">
            <div className="flex justify-between items-end mb-8 pb-4 border-b border-cream-dark/50">
              <div>
                <span className="text-editorial text-brand-fresa mb-4 block">Lo Último de la Cocina</span>
                <h2 className="text-3xl md:text-4xl font-serif text-ink italic">Nuevas Tentaciones</h2>
              </div>
              <Link href="/search" className="text-sm font-bold uppercase tracking-[0.2em] text-gray-600 hover:text-brand-fresa transition-colors">
                Ver Todas →
              </Link>
            </div>

            {allPosts.length > 0 ? (
              <RecipeGrid posts={recentPosts} initialCount={6} />
            ) : (
              <div className="text-center py-32 bg-white rounded-[2rem] border-2 border-dashed border-cream-dark">
                 <div className="relative w-24 h-24 mx-auto mb-8 opacity-20">
                    <SafeImage src="/images/brand/logo.png" alt="logo" fill className="object-contain grayscale" sizes="96px" />
                 </div>
                 <p className="text-gray-600 font-serif italic text-xl">Nuestra cocina está preparando nuevas delicias...</p>
              </div>
            )}
          </div>

          {/* Sidebar Column */}
          <aside className="w-full lg:w-1/3 space-y-12">
            {/* Author Small Bio Card */}
            <div className="bg-white p-8 rounded-[2rem] border border-cream-dark shadow-sm text-center sticky top-32">
              <div className="relative w-24 h-24 mx-auto mb-6 rounded-full overflow-hidden border-4 border-brand-fresa/5 shadow-inner">
                <SafeImage src={SITE_IMAGES.author} alt="Isabella" fill className="object-cover" sizes="96px" />
              </div>
              <h3 className="text-xl font-serif italic text-ink mb-4">¡Hola! Soy Isabella</h3>
              <p className="text-sm text-gray-600 leading-relaxed font-serif italic mb-8">
                "Bienvenido a mi espacio digital. Aquí comparto mi pasión por la cocina española y mis secretos para platos perfectos."
              </p>
              <Link href="/about" className="text-sm font-bold uppercase tracking-[0.3em] text-brand-fresa border-b border-brand-fresa/20 pb-1">
                Conóceme mejor
              </Link>
            </div>

            {/* Popular Categories Small List */}
            <div className="space-y-8">
              <h4 className="text-sm font-bold uppercase tracking-[0.4em] text-ink text-center border-b border-cream-dark pb-4">Favoritos de Siempre</h4>
              <div className="space-y-4">
                {['Pasteles', 'Galletas', 'Chocolates', 'Postres'].map((cat) => (
                  <Link 
                    key={cat} 
                    href={`/categoria/${cat.toLowerCase()}`}
                    className="flex items-center justify-between p-4 bg-white rounded-xl border border-cream-dark hover:border-brand-fresa/20 hover:translate-x-2 transition-all duration-500 group"
                  >
                    <span className="font-serif italic text-ink group-hover:text-brand-fresa transition-colors">{cat}</span>
                    <span className="text-gray-600 group-hover:text-brand-fresa transition-colors">→</span>
                  </Link>
                ))}
              </div>
            </div>
          </aside>

        </div>
      </section>

      {/* Middle Banner: Cooking Philosophy */}
      <section className="bg-ink text-white py-12 md:py-16 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-brand-fresa/5 rounded-full blur-[120px]" />
        <div className="container mx-auto px-6 text-center relative z-10">
          <div className="max-w-3xl mx-auto space-y-8">
            <span className="text-sm font-bold uppercase tracking-[0.6em] text-brand-fresa">Excelencia Técnica</span>
            <h2 className="text-3xl md:text-4xl font-serif italic">"El secreto no está solo en los ingredientes, sino en el respeto por el proceso."</h2>
            <div className="w-16 h-px bg-white/20 mx-auto" />
            <p className="text-white/70 font-serif italic text-base md:text-lg">
              En RecetaDolce, cada paso está diseñado para garantizar que tu tiempo en la cocina sea un éxito absoluto.
            </p>
          </div>
        </div>
      </section>

      {/* Categories Spotlight */}
      <section className="py-16 md:py-24 bg-white border-b border-cream-dark/30">
        <div className="container mx-auto px-4 md:px-8 max-w-7xl">
           <div className="text-center mb-16">
              <span className="text-editorial text-brand-fresa mb-4 block">Colección Editorial</span>
              <h2 className="text-4xl md:text-5xl font-serif italic text-ink">Especialidades</h2>
           </div>
           
           <div className="grid grid-cols-1 md:grid-cols-3 gap-12 lg:gap-16">
              {[
                { name: 'Repostería Fina', img: SITE_IMAGES.categories.reposteria, slug: 'reposteria' },
                { name: 'Chocolate Belga', img: SITE_IMAGES.categories.chocolates, slug: 'chocolates' },
                { name: 'Pastelería de Autor', img: SITE_IMAGES.categories.pasteles, slug: 'pasteles' }
              ].map((item, i) => (
                <Link key={i} href={`/categoria/${item.slug}`} className="group space-y-6 block">
                  <div className="relative aspect-square rounded-[2rem] overflow-hidden shadow-lg border-8 border-cream-base group-hover:border-brand-fresa/10 transition-all duration-700">
                    <SafeImage src={item.img} alt={item.name} fill className="object-cover group-hover:scale-105 transition-transform duration-[3000ms]" sizes="(max-width: 768px) 100vw, 33vw" />
                    <div className="absolute inset-0 bg-brand-fresa/10 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                  <h3 className="text-2xl font-serif italic text-center text-ink group-hover:text-brand-fresa transition-colors">{item.name}</h3>
                </Link>
              ))}
           </div>
        </div>
      </section>

      <NewsletterSection />

      {/* Authority & Verification Section — EEAT Alignment */}
      <div className="container mx-auto px-4 md:px-8 max-w-7xl">
        <EEATSignals />
      </div>

      {/* Signature Final Quote */}
      <section className="py-16 md:py-24 px-6 text-center border-t border-cream-dark/30 bg-cream-base">
        <div className="container mx-auto max-w-4xl">
          <div className="fresa-dot mb-8 scale-150" />
          <h2 className="text-3xl md:text-4xl lg:text-5xl font-serif italic text-ink leading-tight mb-10">
            "Compartir una comida es la forma más antigua <br className="hidden md:block" /> y honesta de decir 'te quiero'."
          </h2>
          <div className="flex flex-col items-center">
            <div className="relative w-40 h-16 grayscale opacity-40 hover:opacity-100 transition-opacity cursor-default mb-6 flex items-center justify-center">
               <span className="text-3xl md:text-4xl font-serif italic text-ink">Isabella D.</span>
            </div>
            <span className="text-xs md:text-sm font-bold uppercase tracking-[0.4em] text-gray-600">Equipo Editorial · RecetaDolce Studio</span>
          </div>
        </div>
      </section>
    </main>
  );
}
