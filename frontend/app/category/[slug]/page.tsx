import SafeImage from '@/components/SafeImage';
import { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { Post } from '@/types';
import Link from 'next/link';
import SchemaMarkup from '@/components/SchemaMarkup';
import StandardRecipeCard from '@/components/StandardRecipeCard';
import NewsletterSection from '@/components/NewsletterSection';

export const revalidate = 60;

const EMPTY_CATEGORY_IMAGE = 'https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282752/RecetaDolce/mediterranean_ingredients_fallback.jpg';

const CATEGORY_MAP: Record<string, { label: string; description: string; image: string }> = {
  'aperitivos': { 
    label: 'Aperitivos', 
    description: 'Pequeños bocados de gran sabor, el corazón de la cultura social española.',
    image: '/images/cat-tapas-pinchos.jpg'
  },
  'arroces': { 
    label: 'Arroces', 
    description: 'El arte del grano perfecto, desde la costa valenciana hasta tu mesa.',
    image: '/images/cat-arroces-paella.jpg'
  },
  'carnes': { 
    label: 'Carnes', 
    description: 'Cortes seleccionados y preparaciones robustas para los paladares más exigentes.',
    image: '/images/cat-carnes.jpg'
  },
  'pescados': { 
    label: 'Pescados', 
    description: 'Joyas del mar preparadas con la frescura y sencillez que merecen.',
    image: '/images/cat-mariscos.jpg'
  },
  'ensaladas': { 
    label: 'Ensaladas', 
    description: 'Opciones ligeras, nutritivas y frescas que celebran el producto de temporada.',
    image: '/images/cat-saludable.jpg'
  },
  'postres': { 
    label: 'Postres', 
    description: 'Dulces tentaciones que cierran cada comida con un toque de elegancia.',
    image: '/images/cat-postres.jpg'
  }
};

async function getPostsByCategory(categorySlug: string) {
  const { data: posts } = await supabase
    .from('posts')
    .select('*, categories!inner(slug)')
    .eq('is_published', true)
    .eq('categories.slug', categorySlug)
    .order('published_at', { ascending: false });
  return (posts as Post[]) || [];
}

const BASE_URL = 'https://RecetaDolce.com';

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const categoryData = CATEGORY_MAP[slug];
  
  if (!categoryData) return { title: 'Categoría No Encontrada' };

  const canonicalUrl = `${BASE_URL}/category/${slug}`;
  const ogImage = `${BASE_URL}${categoryData.image}`;
  const keywords = [
    categoryData.label.toLowerCase(),
    `recetas de ${categoryData.label.toLowerCase()}`,
    `${categoryData.label.toLowerCase()} españolas`,
    'recetas españolas', 'cocina española', 'gastronomía española',
  ];

  return {
    title: `${categoryData.label} — Recetas Españolas Auténticas | RecetaDolce`,
    description: `${categoryData.description} Descubre las mejores recetas de ${categoryData.label.toLowerCase()} con técnica profesional y sabor auténtico.`,
    keywords,
    alternates: { canonical: canonicalUrl },
    openGraph: {
      title: `${categoryData.label} | RecetaDolce`,
      description: categoryData.description,
      url: canonicalUrl,
      siteName: 'RecetaDolce',
      locale: 'es_ES',
      type: 'website',
      images: [{ url: ogImage, width: 1200, height: 630, alt: `${categoryData.label} - Recetas españolas en RecetaDolce` }],
    },
    twitter: {
      card: 'summary_large_image',
      title: `${categoryData.label} | RecetaDolce`,
      description: categoryData.description,
      images: [ogImage],
    },
    robots: { index: true, follow: true },
  };
}


export default async function CategoryPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const categoryData = CATEGORY_MAP[slug];
  
  if (!categoryData) {
    notFound();
  }

  const posts = await getPostsByCategory(slug);

  // CollectionPage + BreadcrumbList schema
  const collectionSchema = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "CollectionPage",
        "@id": `${BASE_URL}/category/${slug}`,
        "name": `${categoryData.label} | RecetaDolce`,
        "description": categoryData.description,
        "url": `${BASE_URL}/category/${slug}`,
        "inLanguage": "es-ES",
        "publisher": { "@type": "Organization", "name": "RecetaDolce", "url": BASE_URL },
        "hasPart": posts.map(p => ({
          "@type": "Recipe",
          "name": p.title,
          "url": `${BASE_URL}/${p.slug}`,
          "image": p.hero_image || undefined,
          "description": p.excerpt || undefined,
        }))
      },
      {
        "@type": "BreadcrumbList",
        "itemListElement": [
          { "@type": "ListItem", "position": 1, "name": "Inicio", "item": BASE_URL },
          { "@type": "ListItem", "position": 2, "name": categoryData.label, "item": `${BASE_URL}/category/${slug}` }
        ]
      }
    ]
  };

  return (
    <main className="min-h-screen bg-cream-base pb-16">
      <SchemaMarkup type="CollectionPage" data={collectionSchema} />
      
      {/* Editorial Header Section */}
      <section className="relative h-[35vh] min-h-[300px] overflow-hidden flex items-center justify-center">
        {/* Background Image with Ken Burns effect */}
        <div className="absolute inset-0 z-0">
          <SafeImage
            src={categoryData.image}
            alt={categoryData.label}
            fill
            className="object-cover transition-transform duration-[10000ms] scale-110 group-hover:scale-100"
            priority
            sizes="100vw"
          />
          {/* Multi-layered overlay for depth */}
          <div className="absolute inset-0 bg-gradient-to-b from-black/20 via-transparent to-black/60" />
          <div className="absolute inset-0 backdrop-blur-[2px]" />
        </div>

        {/* Floating Content Card */}
        <div className="relative container mx-auto px-6 z-10 flex justify-center">
          <div className="max-w-3xl bg-white/10 backdrop-blur-3xl p-6 md:p-10 rounded-[2.5rem] border border-white/20 text-center animate-fade-up shadow-[0_50px_100px_rgba(0,0,0,0.3)]">
            <div className="inline-block px-8 py-2 bg-brand-fresa text-white text-sm font-bold uppercase tracking-[0.5em] rounded-full mb-6 shadow-2xl">
              Colección Especial
            </div>
            
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-serif text-white mb-4 leading-none tracking-tighter drop-shadow-2xl">
              {categoryData.label}
            </h1>
            
            <div className="w-32 h-px bg-white/40 mx-auto mb-6" />
            
            <p className="max-w-xl mx-auto text-white font-serif italic text-lg md:text-xl leading-relaxed opacity-90 drop-shadow-lg">
              &ldquo;{categoryData.description}&rdquo;
            </p>
            
            <div className="mt-12 flex items-center justify-center space-x-6 text-white/90 text-sm font-bold uppercase tracking-[0.3em]">
              <span>{posts.length} Recetas</span>
              <span className="w-1.5 h-1.5 bg-brand-fresa rounded-full" />
              <span>Técnica Profesional</span>
            </div>
          </div>
        </div>
        
        {/* Bottom edge shadow */}
        <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-cream-base to-transparent z-20" />
      </section>

      {/* Recipe Grid */}
      <section className="container mx-auto px-6 -mt-8 relative z-30">
        {posts.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-x-6 gap-y-10">
            {posts.map((post, i) => (
              <div key={post.id} className="animate-fade-up" style={{ animationDelay: `${i * 0.1}s` }}>
                <StandardRecipeCard post={post} />
              </div>
            ))}
          </div>
        ) : (

          <div className="max-w-4xl mx-auto text-center py-40 glass-fresa rounded-[3rem] border border-brand-fresa/10">
            <div className="relative w-32 h-32 mx-auto mb-8 opacity-50 grayscale">
              <SafeImage src={EMPTY_CATEGORY_IMAGE} alt="Categoría vacía" fill sizes="128px" className="object-contain" />
            </div>
            <p className="text-gray-600 font-serif text-2xl italic mb-12">
              Nuestra despensa de {categoryData.label.toLowerCase()} está siendo renovada. <br />
              Vuelve pronto para descubrir nuevas delicias.
            </p>
            <Link 
              href="/" 
              className="inline-block px-10 py-4 bg-brand-fresa text-white font-bold uppercase tracking-widest text-sm rounded-full hover:bg-brand-red transition-all shadow-xl shadow-brand-fresa/20"
            >
              Explorar otras joyas
            </Link>
          </div>
        )}
      </section>
      <NewsletterSection />
    </main>
  );
}
