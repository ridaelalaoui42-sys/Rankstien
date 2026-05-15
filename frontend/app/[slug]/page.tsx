import { Metadata } from 'next';
import Image from 'next/image';
import SafeImage from '@/components/SafeImage';
import FloatingNewsletter from '@/components/FloatingNewsletter';
import EEATSignals from '@/components/EEATSignals';
import { notFound } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { Post } from '@/types';
import SchemaMarkup from '@/components/SchemaMarkup';
import RecipeDetails from '@/components/RecipeDetails';
import { marked } from 'marked';
import { sanitize } from '@/lib/sanitize';
import { calculateReadTime, slugify } from '@/lib/utils';
import { getCategoryUrl, getCategoryLabel, getCategorySlug } from '@/lib/categories';
import ReadingProgress from '@/components/ReadingProgress';
import ShareMenu from '@/components/ShareMenu';
import RelatedRecipes from '@/components/recipe/RelatedRecipes';
import AuthorBio from '@/components/AuthorBio';
import ReviewSystem from '@/components/ReviewSystem';
import Breadcrumbs from '@/components/Breadcrumbs';
import { FaStar, FaUtensils, FaCheckCircle } from 'react-icons/fa';
import Link from 'next/link';
import NewsletterSection from '@/components/NewsletterSection';
import Sidebar from '@/components/Sidebar';
import PrintLink from '@/components/recipe/PrintLink';
import DeterministicDate from '@/components/DeterministicDate';
import PinterestPin from '@/components/PinterestPin';
import AdUnit from '@/components/AdUnit';
import { getSettings } from '@/lib/settings';
import { SITE_IMAGES } from '@/lib/siteImages';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateStaticParams() {
  try {
    const { data: posts, error } = await supabase
      .from('posts')
      .select('slug')
      .eq('is_published', true)
      .order('published_at', { ascending: false })
      .limit(20);

    if (error) {
      console.error('generateStaticParams error:', error);
      return [];
    }

    return (posts || []).map((post: { slug: string }) => ({
      slug: post.slug,
    }));
  } catch (err) {
    console.error('generateStaticParams crash:', err);
    return [];
  }
}

interface PageProps {
  params: Promise<{ slug: string }>;
}

async function getPost(slug: string) {
  try {
    const { data: post, error } = await supabase
      .from('posts')
      .select('*, categories(name, slug)')
      .eq('slug', slug)
      .eq('is_published', true)
      .maybeSingle();

    if (error) {
      console.error('getPost error:', error);
      return null;
    }
    return post;
  } catch (err) {
    console.error('getPost crash:', err);
    return null;
  }
}

async function getFeaturedPosts(excludeSlug: string) {
  try {
    const { data, error } = await supabase
      .from('posts')
      .select('title, slug, hero_image')
      .eq('is_published', true)
      .neq('slug', excludeSlug)
      .order('published_at', { ascending: false })
      .limit(3);
    if (error) return [];
    return data || [];
  } catch {
    return [];
  }
}


export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const post = await getPost(slug);
  
  if (!post) return { title: 'Post Not Found' };

  const canonicalUrl = `${process.env.NEXT_PUBLIC_BASE_URL || 'https://recetadolce.com'}/${post.slug}`;

  return {
    title: post.meta_title || post.title,
    description: post.meta_description || post.excerpt,
    keywords: Array.isArray(post.keywords) ? post.keywords : [],
    alternates: {
      canonical: canonicalUrl,
    },
    openGraph: {
      type: 'article',
      title: post.title,
      description: post.excerpt || post.meta_description || '',
      url: canonicalUrl,
      siteName: 'RecetaDolce',
      locale: 'es_ES',
      publishedTime: post.created_at,
      modifiedTime: post.updated_at || post.created_at,
      authors: ['Isabella Dolce'],
      section: post.categories?.name || 'Recetas',
      images: post.hero_image
        ? [{ url: post.hero_image, width: 1200, height: 630, alt: `Receta de ${post.title} paso a paso — RecetaDolce` }]
        : [],
    },
    twitter: {
      card: 'summary_large_image',
      title: post.title,
      description: post.excerpt || '',
      images: post.hero_image ? [post.hero_image] : [],
    },
  };
}


export default async function RecipePage({ params }: PageProps) {
  const { slug } = await params;
  const post = await getPost(slug);
  if (!post) notFound();

  const settings = await getSettings();
  const featuredPosts = await getFeaturedPosts(slug);

  // Handle JSON parsing for recipe schema with extra safety
  let recipeSchema = null;
  if (post.recipe_schema) {
    try {
      recipeSchema = typeof post.recipe_schema === 'string' 
        ? JSON.parse(post.recipe_schema) 
        : post.recipe_schema;
    } catch (err) {
      console.error('Recipe schema JSON parse error:', err);
      recipeSchema = null;
    }
  }

  const formatTime = (time: any) => {
    if (!time) return undefined;
    if (typeof time === 'string' && time.startsWith('PT')) return time;
    const match = String(time).match(/\d+/);
    return match ? `PT${match[0]}M` : undefined;
  };

  const avgRating = (post.rating_count && post.rating_count > 0 && post.rating_value) 
    ? (post.rating_value / post.rating_count).toFixed(1) 
    : "4.9";
  const ratingCount = (post.rating_count && post.rating_count > 0) 
    ? post.rating_count.toString() 
    : "24";

  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'https://RecetaDolce.com';
  const fullUrl = `${baseUrl}/${post.slug}`;

  // Enhanced cleaning: Remove the last image and its containing link if it's a Pinterest-style button
  const imgRegex = /!\[.*?\]\((.*?)\)/g;
  const linkImgRegex = /\[\s*!\[.*?\]\((.*?)\)\s*\]\((.*?)\)/g;
  let processedContent = post.content || '';

  // Extract Pinterest Pin ID from an embedded iframe or URL if the user pasted it
  let customPinId = post.pinterest_pin_id;
  const pinterestIframeRegex = /<iframe[^>]*src="[^"]*pinterest\.com\/ext\/embed\.html\?id=(\d+)"[^>]*>[\s\S]*?<\/iframe>/i;
  const iframeMatch = processedContent.match(pinterestIframeRegex);
  if (iframeMatch) {
    customPinId = iframeMatch[1];
    processedContent = processedContent.replace(iframeMatch[0], '');
  }

  // Extract the image for Pinterest BEFORE cleaning it from the content
  const matches = [...processedContent.matchAll(imgRegex)];
  const lastMatchBeforeCleaning = matches.length > 0 ? matches[matches.length - 1] : null;
  const lastContentImage = lastMatchBeforeCleaning ? lastMatchBeforeCleaning[1] : null;
  
  // First, try to find and remove a linked image (common for Pinterest buttons)
  const linkImgMatches = [...processedContent.matchAll(linkImgRegex)];
  if (linkImgMatches.length > 0) {
    const lastLinkMatch = linkImgMatches[linkImgMatches.length - 1];
    const lastIndex = processedContent.lastIndexOf(lastLinkMatch[0]);
    // If it's near the end of the content (last 500 chars), remove it
    if (lastIndex > processedContent.length - 500) {
      processedContent = processedContent.slice(0, lastIndex) + processedContent.slice(lastIndex + lastLinkMatch[0].length);
    }
  } else if (lastMatchBeforeCleaning) {
    // If no linked image found, fall back to removing just the last image
    const lastIndex = processedContent.lastIndexOf(lastMatchBeforeCleaning[0]);
    if (lastIndex > processedContent.length - 500) {
      processedContent = processedContent.slice(0, lastIndex) + processedContent.slice(lastIndex + lastMatchBeforeCleaning[0].length);
    }
  }

  // Use marked with GFM and explicit options for reliable link parsing
  let pinterestMedia = lastContentImage || post.hero_image;
  if (pinterestMedia && !pinterestMedia.startsWith('http')) {
    pinterestMedia = `${baseUrl}${pinterestMedia.startsWith('/') ? '' : '/'}${pinterestMedia}`;
  }

  let contentHtml = '';
  try {
    const rawHtml = await marked.parse(processedContent, {
      gfm: true,
      breaks: true,
    });
    // CRITICAL SECURITY FIX: Sanitize HTML to prevent Stored XSS
    contentHtml = sanitize(rawHtml);
  } catch (err) {
    console.error('Markdown parsing error:', err);
    contentHtml = sanitize(processedContent);
  }

  // Construct strictly compliant Recipe Schema for Google Rich Results
  let jsonLdSchema: any = null;
  if (recipeSchema) {
    // Safely extract ingredients and instructions
    const rawIngredients = recipeSchema.recipeIngredient || recipeSchema.ingredients || [];
    const rawInstructions = recipeSchema.recipeInstructions || recipeSchema.instructions || [];
    
    // Normalize instructions to HowToStep format
    const formattedInstructions = rawInstructions.map((step: any, index: number) => {
      if (typeof step === 'string') {
        return {
          "@type": "HowToStep",
          "name": `Paso ${index + 1}`,
          "text": step,
          "url": `${fullUrl}#step${index + 1}`
        };
      }
      return {
        "@type": "HowToStep",
        "name": step.name || `Paso ${index + 1}`,
        "text": step.text || step.description || "",
        "url": step.url || `${fullUrl}#step${index + 1}`
      };
    });

    // Extract Keywords
    let keywordsString = "";
    if (Array.isArray(post.keywords)) {
      keywordsString = post.keywords.join(", ");
    } else if (typeof post.keywords === 'string') {
      keywordsString = post.keywords;
    }

    const baseArticleSchema = {
      "@context": "https://schema.org",
      "@type": "Article",
      "headline": post.title,
      "image": [
        pinterestMedia || post.hero_image || `${baseUrl}/images/brand/logo.png`
      ],
      "datePublished": post.created_at,
      "dateModified": post.updated_at || post.created_at,
      "author": [{
          "@type": "Person",
          "name": "Isabella Dolce",
          "jobTitle": "Directora Editorial",
          "url": `${baseUrl}/about`,
          "sameAs": [
            "https://instagram.com/RecetaDolce",
            "https://twitter.com/RecetaDolce"
          ],
          "knowsAbout": [
            "Seguridad Alimentaria",
            "Técnicas de Repostería",
            "Alta Cocina Española"
          ],
          "alumniOf": {
            "@type": "Organization",
            "name": "Le Cordon Bleu"
          }
      }],
      "publisher": {
        "@type": "Organization",
        "name": "RecetaDolce",
        "logo": {
          "@type": "ImageObject",
          "url": `${baseUrl}/images/brand/logo.png`
        }
      },
      "description": post.excerpt || post.meta_description || `Receta de ${post.title}`,
      "mainEntityOfPage": {
        "@type": "WebPage",
        "@id": fullUrl
      }
    };

    let recipeLdSchema: any = null;
    if (recipeSchema) {
      recipeLdSchema = {
        "@context": "https://schema.org/",
        "@type": "Recipe",
        "name": post.title,
        "image": [
          pinterestMedia || post.hero_image || `${baseUrl}/images/brand/logo.png`
        ],
        "author": {
          "@type": "Organization",
          "name": "RecetaDolce",
          "url": baseUrl
        },
        "datePublished": post.created_at,
        "description": post.excerpt || post.meta_description || `Receta de ${post.title}`,
        "prepTime": formatTime(recipeSchema.prepTime) || "PT15M",
        "cookTime": formatTime(recipeSchema.cookTime) || "PT20M",
        "totalTime": formatTime(recipeSchema.totalTime) || "PT35M",
        "recipeYield": recipeSchema.recipeYield || recipeSchema.yields || "4 raciones",
        "recipeCategory": post.categories?.name || "General",
        "recipeCuisine": "Española",
        "keywords": keywordsString,
        "recipeIngredient": rawIngredients.length > 0 ? rawIngredients : ["Ingredientes secretos"],
        "recipeInstructions": formattedInstructions.length > 0 ? formattedInstructions : [
          { "@type": "HowToStep", "name": "Paso 1", "text": "Preparar los ingredientes." }
        ],
        "aggregateRating": {
          "@type": "AggregateRating",
          "ratingValue": avgRating,
          "ratingCount": ratingCount
        }
      };

      // Add optional nutrition if available
      if (recipeSchema.nutrition) {
        recipeLdSchema.nutrition = {
          "@type": "NutritionInformation",
          "calories": typeof recipeSchema.nutrition.calories === 'number' 
            ? `${recipeSchema.nutrition.calories} calories` 
            : (recipeSchema.nutrition.calories || "250 calories")
        };
      }

      // Add optional video if available
      if (recipeSchema.video) {
        recipeLdSchema.video = {
          "@type": "VideoObject",
          "name": post.title,
          "description": post.excerpt || `Video receta de ${post.title}`,
          "thumbnailUrl": [ pinterestMedia || post.hero_image || `${baseUrl}/images/brand/logo.png` ],
          "contentUrl": typeof recipeSchema.video === 'string' ? recipeSchema.video : recipeSchema.video.contentUrl,
          "uploadDate": post.created_at
        };
      }
    }

    // Combine both schemas in an array for the page
    jsonLdSchema = recipeLdSchema ? [baseArticleSchema, recipeLdSchema] : baseArticleSchema;
  }

  return (
    <article className="min-h-screen bg-white pb-32">
      <ReadingProgress />
      <ShareMenu title={post.title} slug={post.slug} />
      
      {/* Article Header - Architectural Excellence */}
      <header className="container mx-auto px-4 md:px-8 pt-10 pb-12 text-center max-w-4xl">
        <div className="mb-8 flex justify-center">
          <Breadcrumbs 
            items={[
              { label: 'Inicio', href: '/' },
              { label: post.categories?.name || 'Recetas', href: `/categoria/${post.categories?.slug || 'general'}` },
              { label: post.title, href: '#' }
            ]} 
          />
        </div>
        
        <h1 className="text-3xl md:text-5xl lg:text-6xl font-serif text-ink mb-10 leading-[1.15] tracking-tight italic">
          {post.title}
        </h1>

        <div className="flex flex-col items-center gap-8">
          <div className="flex items-center justify-center gap-8 text-sm font-bold uppercase tracking-[0.4em] text-gray-600">
            <span className="flex items-center gap-3">
              <FaStar className="text-brand-fresa" size={14} />
              <span className="text-ink">{avgRating}</span> ({ratingCount} VOTOS)
            </span>
            <span className="opacity-30">•</span>
            <DeterministicDate date={post.created_at} />
          </div>

          <div className="flex items-center gap-6 text-sm font-bold uppercase tracking-[0.3em] text-gray-600">
            <span className="px-4 py-1.5 border border-gray-100 rounded-full">{calculateReadTime(post.content || '')} MIN LECTURA</span>
            <PrintLink />
          </div>
        </div>
      </header>

      {/* Featured Image - Premium Presentation */}
      <div className="container mx-auto px-4 md:px-8 mb-12 max-w-5xl">
        <div className="relative aspect-[16/9] md:aspect-[21/9] rounded-[2rem] overflow-hidden shadow-2xl border-[12px] border-cream-base group/hero">
          <SafeImage 
            src={post.hero_image || SITE_IMAGES.homeHero} 
            alt={`Receta de ${post.title} preparada paso a paso — fotografía editorial de RecetaDolce`} 
            fill 
            className="object-cover transition-transform duration-1000 group-hover/hero:scale-105"
            priority
            fetchPriority="high"
            sizes="100vw"
          />
          <div className="absolute inset-0 bg-ink/10 mix-blend-overlay transition-opacity duration-700 group-hover/hero:opacity-0" />
        </div>
      </div>

      <div className="container mx-auto px-4 md:px-8 max-w-6xl">
        <div className="flex flex-col lg:flex-row gap-10 lg:gap-14">
          
          {/* Main Content Area */}
          <div className="flex-1 min-w-0 lg:max-w-3xl">
            {/* Top Ad */}
            {settings?.ads_top_slot && (
              <AdUnit slot={settings.ads_top_slot} label="Publicidad" className="mb-16" />
            )}

            {/* Excerpt/Intro - Editorial Level Typography */}
            <div className="mb-12">
               <p className="text-xl md:text-2xl lg:text-3xl font-serif italic text-gray-600 leading-relaxed tracking-tight max-w-3xl">
                  {post.excerpt}
               </p>
            </div>

            {/* Recipe Details if present */}
            {recipeSchema && (
              <div className="mb-16">
                <RecipeDetails 
                  ingredients={recipeSchema.recipeIngredient || recipeSchema.ingredients || []}
                  instructions={recipeSchema.recipeInstructions || recipeSchema.instructions || []}
                  nutrition={recipeSchema.nutrition}
                  prepTime={recipeSchema.prepTime}
                  cookTime={recipeSchema.cookTime}
                  yields={recipeSchema.recipeYield || recipeSchema.yields}
                  title={post.title}
                />
              </div>
            )}

            {/* Pro Tip Callout */}
            <div className="bg-brand-fresa/5 border-l-4 border-brand-fresa p-8 rounded-r-[2rem] mb-16 italic group">
               <span className="text-editorial text-brand-fresa mb-4 block">Consejo de Chef</span>
               <p className="text-lg text-ink font-serif leading-relaxed mb-4">
                  "Para un resultado verdaderamente profesional, asegúrate de que todos tus ingredientes estén a temperatura ambiente antes de comenzar. La paciencia es el secreto de la excelencia."
               </p>
               <Link href="/guia-higiene" className="text-xs font-bold uppercase tracking-widest text-brand-fresa/60 hover:text-brand-fresa transition-colors">
                  Ver protocolo de higiene profesional →
               </Link>
            </div>

            <div 
              className="prose-editorial max-w-none mb-16"
              dangerouslySetInnerHTML={{ __html: contentHtml }}
            />

            {/* Middle Ad */}
            {settings?.ads_middle_slot && (
              <AdUnit slot={settings.ads_middle_slot} label="Sigue Leyendo" className="mb-16" />
            )}

            {/* Pinterest Pin Section - Renders embed iframe */}
            <PinterestPin pinId={customPinId} />

            <PrintLink className="inline-flex items-center gap-3 px-10 py-5 bg-ink text-white rounded-full text-sm font-bold uppercase tracking-[0.3em] hover:bg-brand-fresa transition-all shadow-xl mb-20" />

            {/* Authority & Verification Section — EEAT Alignment */}
            <EEATSignals />

            {/* Author Section */}
            <div className="border-t border-cream-dark pt-12 mb-16">
              <AuthorBio />
            </div>

            {/* Review Section */}
            <ReviewSystem postId={post.id} />

            {/* Bottom Ad */}
            {settings?.ads_bottom_slot && (
              <AdUnit slot={settings.ads_bottom_slot} label="Recomendado" className="mt-16" />
            )}
          </div>

          {/* Sidebar */}
          <div className="w-full lg:w-[350px] space-y-12">
            {settings?.ads_sidebar_slot && (
              <AdUnit slot={settings.ads_sidebar_slot} label="Publicidad" />
            )}
            <Sidebar featuredPosts={featuredPosts} />
          </div>

        </div>
      </div>

      {/* Recommended Section */}
      <RelatedRecipes currentSlug={post.slug} />
      
      <NewsletterSection />

      {jsonLdSchema && <SchemaMarkup type="Recipe" data={jsonLdSchema} />}

      {/* BreadcrumbList structured data for Google SERP breadcrumbs */}
      <SchemaMarkup type="BreadcrumbList" data={{
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
          { "@type": "ListItem", "position": 1, "name": "Inicio", "item": baseUrl },
          { "@type": "ListItem", "position": 2, "name": post.categories?.name || 'Recetas', "item": `${baseUrl}/categoria/${post.categories?.slug || 'general'}` },
          { "@type": "ListItem", "position": 3, "name": post.title, "item": fullUrl }
        ]
      }} id="schema-breadcrumb" />
    </article>
  );
}
