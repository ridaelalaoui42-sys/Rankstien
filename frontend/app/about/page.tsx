import { Metadata } from 'next';
import SafeImage from '@/components/SafeImage';
import Link from 'next/link';
import NewsletterSection from '@/components/NewsletterSection';
import { FaInstagram, FaPinterestP, FaFacebookF, FaUtensils, FaHeart, FaCheckCircle } from 'react-icons/fa';
import { SITE_IMAGES } from '@/lib/siteImages';

export const metadata: Metadata = {
  title: 'Sobre Isabella Dolce | El Alma de RecetaDolce',
  description: 'Conoce a Isabella Dolce: su pasión por la cocina, su viaje gastronómico y por qué cada receta en RecetaDolce es una garantía de éxito en tu mesa.',
  alternates: {
    canonical: 'https://RecetaDolce.com/about',
  },
};

export default function AboutPage() {
  return (
    <main className="min-h-screen bg-cream-base">
      {/* RecipeTin Eats Style Hero */}
      <section className="pt-24 pb-20 md:pt-40 md:pb-32 px-6 border-b border-cream-dark/50 bg-white">
        <div className="container mx-auto max-w-5xl">
          <div className="flex flex-col md:flex-row items-center gap-16 md:gap-24">
            <div className="w-full md:w-1/2">
              <span className="text-editorial text-brand-fresa mb-6 block">Conoce a la Fundadora</span>
              <h1 className="text-6xl md:text-8xl font-serif text-ink mb-10 italic leading-[0.9]">
                Hola, soy <br />
                <span className="text-fresa-gradient">Isabella</span>.
              </h1>
              <p className="text-2xl font-serif text-gray-600 italic leading-relaxed">
                "Mi misión es simple: que cocines platos increíbles que dejen a todos pidiendo más, sin que tengas que pasar horas estresado en la cocina."
              </p>
            </div>
            <div className="w-full md:w-1/2 relative">
              <div className="relative aspect-[4/5] rounded-[3rem] overflow-hidden shadow-[0_50px_100px_rgba(164,19,60,0.15)] transform rotate-2">
                <SafeImage 
                  src={SITE_IMAGES.author}
                  alt="Isabella Dolce portrait"
                  fill
                  sizes="(max-width: 768px) 100vw, 50vw"
                  className="object-cover"
                  priority
                />
              </div>
              <div className="absolute -bottom-10 -left-10 w-40 h-40 bg-brand-fresa/5 rounded-full blur-3xl -z-10" />
            </div>
          </div>
        </div>
      </section>

      <section className="py-24 md:py-40 px-6">
        <div className="container mx-auto max-w-6xl">
          <div className="flex flex-col lg:flex-row gap-20 items-start">
            
            {/* Main Content Area */}
            <div className="w-full lg:w-2/3 prose-editorial">
              <h2 className="text-4xl font-serif text-ink mb-12 italic border-b border-brand-fresa/10 pb-6">Mi Filosofía: Cocina con Sentido</h2>
              
              <p className="text-xl text-gray-700 mb-10 leading-relaxed font-serif">
                Si estás buscando recetas pretenciosas con ingredientes que solo se encuentran en tiendas especializadas, este no es tu sitio. Aquí celebramos la <strong>comida real</strong>.
              </p>

              <div className="relative aspect-video w-full mb-12 rounded-[2.5rem] overflow-hidden shadow-2xl">
                 <SafeImage 
                   src={SITE_IMAGES.kitchen} 
                   alt="Isabella cocinando en su estudio" 
                   fill 
                   sizes="(max-width: 1024px) 100vw, 800px"
                   className="object-cover"
                 />
                 <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
                 <span className="absolute bottom-6 left-10 text-white text-sm font-bold uppercase tracking-[0.4em]">En mi elemento · Barcelona 2026</span>
              </div>

              <p className="mb-8">
                Crecí en una casa donde la cocina era el centro del universo. Mi abuela me enseñó que un chorrito de un buen aceite de oliva virgen extra y una pizca de paciencia pueden transformar el ingrediente más humilde en un festín real.
              </p>

              <p className="mb-12">
                Después de años trabajando en el mundo editorial gastronómico, me di cuenta de algo: las recetas suelen fallar porque omiten los pequeños detalles. Esos "secretos" que los chefs dan por sentados pero que marcan la diferencia entre un bizcocho seco y uno que se deshace en la boca. <strong>En RecetaDolce, yo elimino las dudas.</strong>
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-10 my-20">
                <div className="bg-white p-10 rounded-[2.5rem] border border-cream-dark shadow-sm hover:shadow-xl transition-all duration-500">
                  <FaUtensils className="text-brand-fresa mb-6" size={24} />
                  <h3 className="text-xl font-serif italic mb-4">Ingredientes Reales</h3>
                  <p className="text-sm text-gray-600 leading-relaxed">Uso lo que tienes en tu despensa. Si es raro, te daré un sustituto.</p>
                </div>
                <div className="bg-white p-10 rounded-[2.5rem] border border-cream-dark shadow-sm hover:shadow-xl transition-all duration-500">
                  <FaCheckCircle className="text-brand-fresa mb-6" size={24} />
                  <h3 className="text-xl font-serif italic mb-4">Pruebas Infalibles</h3>
                  <p className="text-sm text-gray-600 leading-relaxed">Cada receta se prueba al menos 3 veces antes de ser publicada.</p>
                </div>
              </div>

              <h2 className="text-4xl font-serif text-ink mb-12 italic border-b border-brand-fresa/10 pb-6">Un Poco Sobre Mí</h2>
              <p className="mb-8">
                Cuando no estoy en la cocina manchada de harina, probablemente me encuentres paseando por los mercados locales de Barcelona, buscando la fresa más roja o el tomate más aromático. Soy una firme creyente de que la estacionalidad no es una moda, sino la clave del sabor.
              </p>
              
              <blockquote className="my-16 p-12 bg-brand-fresa/5 rounded-3xl border-l-4 border-brand-fresa">
                <p className="text-2xl text-brand-fresa-deep font-serif italic mb-0">
                  "Cocinar es un acto de generosidad. Cuando preparas algo para alguien, le estás entregando una parte de tu tiempo y de tu corazón."
                </p>
              </blockquote>

              <p className="mb-12">
                Mi mayor alegría es recibir vuestros correos y mensajes diciendo que habéis conseguido hacer ese postre que siempre os pareció imposible, o que vuestros hijos han repetido plato. Esa es la verdadera estrella Michelin para mí.
              </p>
              
              {/* E-E-A-T Commitment Section */}
              <div className="bg-cream-soft/50 border border-brand-fresa/10 p-10 md:p-14 rounded-[3rem] mb-16">
                <h3 className="text-2xl font-serif italic text-ink mb-6 flex items-center">
                  <FaCheckCircle className="text-brand-fresa mr-4" /> Compromiso con la Excelencia y Seguridad
                </h3>
                <p className="text-gray-600 mb-8 leading-relaxed italic font-serif">
                  "No solo buscamos el sabor perfecto, sino la absoluta tranquilidad de quienes confían en mis recetas. Cada técnica y consejo sigue rigurosamente los estándares de seguridad vigentes."
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <Link 
                    href="/seguridad-alimentaria" 
                    className="p-6 bg-white rounded-2xl border border-brand-fresa/5 hover:border-brand-fresa/20 transition-all group"
                  >
                    <h4 className="text-sm font-bold text-ink mb-2 uppercase tracking-wider">Marco de Seguridad</h4>
                    <p className="text-[10px] text-gray-600 mb-4 leading-relaxed">Conoce nuestro cumplimiento con AESAN, BOE y normativas europeas.</p>
                    <span className="text-[10px] font-bold text-brand-fresa uppercase tracking-widest flex items-center group-hover:translate-x-1 transition-transform">
                      LEER MÁS →
                    </span>
                  </Link>
                  <Link 
                    href="/guia-higiene" 
                    className="p-6 bg-white rounded-2xl border border-brand-fresa/5 hover:border-brand-fresa/20 transition-all group"
                  >
                    <h4 className="text-sm font-bold text-ink mb-2 uppercase tracking-wider">Protocolos de Higiene</h4>
                    <p className="text-[10px] text-gray-600 mb-4 leading-relaxed">Guía técnica de manipulación profesional adaptada a tu cocina.</p>
                    <span className="text-[10px] font-bold text-brand-fresa uppercase tracking-widest flex items-center group-hover:translate-x-1 transition-transform">
                      VER GUÍA →
                    </span>
                  </Link>
                </div>
              </div>

              <div className="bg-white border-2 border-cream-dark p-12 rounded-[3rem] text-center">
                <FaHeart className="text-brand-fresa mx-auto mb-8 animate-pulse" size={32} />
                <h3 className="text-2xl font-serif italic mb-6 text-ink">¿Empezamos a cocinar?</h3>
                <p className="text-gray-600 mb-10 font-serif">Explora mis recetas favoritas y descubre lo fácil que es crear magia en tu propia cocina.</p>
                <Link 
                  href="/" 
                  className="inline-block px-12 py-5 bg-brand-fresa text-white rounded-full font-bold uppercase tracking-[0.3em] text-sm hover:bg-brand-red transition-all shadow-xl shadow-brand-fresa/20"
                >
                  Ver mis Recetas
                </Link>
              </div>
            </div>

            {/* Sticky Sidebar */}
            <aside className="w-full lg:w-1/3 lg:sticky lg:top-32 space-y-12">
              <div className="bg-white p-12 rounded-[3rem] border border-cream-dark shadow-sm text-center">
                <div className="relative w-32 h-32 mx-auto mb-8 rounded-full overflow-hidden border-4 border-brand-fresa/10">
                  <SafeImage src={SITE_IMAGES.author} alt="Isabella" fill sizes="128px" className="object-cover" />
                </div>
                <h3 className="text-2xl font-serif italic text-ink mb-2">Isabella Dolce</h3>
                <p className="text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa mb-8">Fundadora · RecetaDolce</p>
                <div className="flex justify-center space-x-6 text-gray-600">
                  <a href="#" className="hover:text-brand-fresa transition-colors" aria-label="Instagram"><FaInstagram size={20} /></a>
                  <a href="#" className="hover:text-brand-fresa transition-colors" aria-label="Pinterest"><FaPinterestP size={20} /></a>
                  <a href="#" className="hover:text-brand-fresa transition-colors" aria-label="Facebook"><FaFacebookF size={20} /></a>
                </div>
              </div>

              <div className="bg-ink text-white p-12 rounded-[3rem] relative overflow-hidden">
                <div className="absolute top-0 right-0 w-32 h-32 bg-brand-fresa/10 rounded-full -mr-16 -mt-16 blur-2xl" />
                <h3 className="text-xl font-serif italic mb-6 relative z-10">Pregúntame cualquier cosa</h3>
                <p className="text-white/70 text-sm leading-relaxed mb-8 relative z-10 italic">
                  ¿Tienes dudas sobre una técnica? ¿No encuentras un ingrediente? Escríbeme y estaré encantada de ayudarte.
                </p>
                <Link href="/contact" className="text-brand-fresa font-bold uppercase tracking-widest text-xs hover:text-white transition-colors">
                  Enviar Mensaje →
                </Link>
              </div>
            </aside>

          </div>
        </div>
      </section>

      <NewsletterSection />
    </main>
  );
}
