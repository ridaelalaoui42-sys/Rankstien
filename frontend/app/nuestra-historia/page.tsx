
import { Metadata } from 'next';
import SafeImage from '@/components/SafeImage';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Nuestra Historia | RecetaDolce - El Arte de la Cocina Española',
  description: 'Descubra el viaje sensorial de RecetaDolce, desde una pequeña cocina familiar en la Costa Brava hasta convertirnos en la referencia editorial de la alta gastronomía casera.',
  alternates: {
    canonical: 'https://RecetaDolce.com/nuestra-historia',
  },
};

export default function HistoryPage() {
  return (
    <main className="min-h-screen bg-cream-base">
      {/* Narrative Hero */}
      <section className="relative pt-32 pb-24 px-6 text-center overflow-hidden">
        <div className="absolute inset-0 bg-brand-fresa/5 opacity-40 blur-[120px] -z-10 animate-pulse" />
        <div className="container mx-auto max-w-4xl">
          <span className="text-editorial text-brand-fresa mb-8 block uppercase tracking-[0.5em] text-sm">Un Legado de Pasión</span>
          <h1 className="text-6xl md:text-8xl lg:text-9xl font-serif text-ink mb-16 leading-[0.9] tracking-tightest">
            Nuestra <br />
            <span className="text-fresa-gradient italic font-light">Esencia</span>
          </h1>
          <div className="w-40 h-px bg-brand-fresa mx-auto mb-16 opacity-20" />
          <p className="text-xl md:text-3xl font-serif text-gray-600 italic leading-relaxed max-w-3xl mx-auto tracking-tight">
            "En RecetaDolce, creemos que la cocina no es solo nutrición, sino un lenguaje de amor, una danza de texturas y el suspiro de una fresa madura encontrando su crema perfecta."
          </p>
        </div>
      </section>

      {/* Philosophy Section */}
      <section className="py-32 px-6 bg-white border-y border-brand-fresa/5">
        <div className="container mx-auto max-w-6xl">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-24 items-center">
            <div className="relative aspect-[3/4] rounded-[4rem] overflow-hidden shadow-2xl group">
              <SafeImage 
                src="https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282800/RecetaDolce/vintage_family_cooking.jpg"
                alt="El origen en la cocina tradicional"
                fill
                sizes="(max-width: 768px) 100vw, 50vw"
                className="object-cover group-hover:scale-105 transition-transform duration-[3000ms]"
              />
              <div className="absolute inset-0 bg-brand-fresa/10 mix-blend-overlay" />
            </div>
            <div className="space-y-10">
              <h2 className="text-3xl md:text-5xl font-serif text-ink leading-tight">
                El Comienzo: <br />
                <span className="italic text-brand-fresa">Sabor de Infancia</span>
              </h2>
              <p className="text-lg text-gray-600 font-serif italic leading-relaxed">
                Nuestra historia no nació en una escuela culinaria de renombre, sino en el calor de una cocina familiar en la Costa Brava. Allí, entre el rumor del Mediterráneo y el aroma del pan recién horneado, aprendimos que el ingrediente más importante siempre es el tiempo.
              </p>
              <p className="text-lg text-gray-600 font-serif italic leading-relaxed">
                Cada receta en nuestra colección es un fragmento de esa memoria, refinada por años de experimentación técnica pero fiel a su alma rústica y honesta.
              </p>
              <div className="pt-8">
                <div className="h-px w-24 bg-brand-fresa/30 mb-8" />
                <span className="text-sm font-bold uppercase tracking-[0.4em] text-brand-fresa">Isabella Dolce · Fundadora</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* The Pillars */}
      <section className="py-40 px-6 bg-cream-ripple">
        <div className="container mx-auto max-w-6xl">
          <div className="text-center mb-24">
            <h2 className="text-4xl md:text-5xl font-serif text-ink mb-6">Nuestros Pilares</h2>
            <div className="w-16 h-1 bg-brand-fresa mx-auto" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-16">
            {[
              { 
                title: 'Excelencia Editorial', 
                desc: 'Cada instrucción es probada rigurosamente para garantizar que el resultado en su mesa sea impecable.',
                icon: '◈'
              },
              { 
                title: 'Estética Visual', 
                desc: 'Creemos que la comida entra por los ojos. Nuestra fotografía busca capturar el alma del ingrediente.',
                icon: '✧'
              },
              { 
                title: 'Herencia y Evolución', 
                desc: 'Honramos las raíces españolas mientras abrazamos técnicas contemporáneas de la alta cocina.',
                icon: '❀'
              }
            ].map((pillar, i) => (
              <div key={i} className="text-center space-y-6 group">
                <div className="text-4xl text-brand-fresa/30 group-hover:text-brand-fresa transition-colors duration-500">{pillar.icon}</div>
                <h3 className="text-xl font-serif text-ink italic">{pillar.title}</h3>
                <p className="text-sm text-gray-600 font-serif italic leading-loose opacity-80">
                  {pillar.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Timeline Section */}
      <section className="py-40 px-6 bg-ink text-white relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-brand-fresa/10 rounded-full -mr-48 -mt-48 blur-[120px]" />
        <div className="container mx-auto max-w-5xl relative z-10">
          <div className="space-y-40">
            
            {/* 1994 */}
            <div className="flex flex-col md:flex-row items-center gap-20">
              <div className="flex-1 space-y-8 order-2 md:order-1 text-center md:text-left">
                <span className="text-5xl md:text-6xl font-serif text-brand-fresa/30 block tracking-tighter">1994</span>
                <h2 className="text-3xl md:text-4xl font-serif italic">El Primer Cuaderno</h2>
                <p className="text-white/70 font-serif italic leading-loose text-lg">
                  Todo comenzó con un cuaderno de cuero rojo donde se anotaron las primeras 50 recetas de la abuela. No eran solo medidas, eran consejos susurrados sobre cómo saber cuándo la crema está en su punto exacto.
                </p>
              </div>
              <div className="flex-1 relative aspect-square rounded-[4rem] overflow-hidden shadow-2xl order-1 md:order-2 w-full max-w-md mx-auto">
                <SafeImage 
                  src="https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282820/RecetaDolce/classic_ingredients.jpg"
                  alt="Ingredientes clásicos"
                  fill
                  sizes="(max-width: 768px) 100vw, 400px"
                  className="object-cover"
                />
              </div>
            </div>

            {/* Hoy */}
            <div className="flex flex-col md:flex-row items-center gap-20">
              <div className="flex-1 relative aspect-square rounded-[4rem] overflow-hidden shadow-2xl w-full max-w-md mx-auto">
                <SafeImage 
                  src="https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282830/RecetaDolce/modern_studio.jpg"
                  alt="Plato moderno de alta cocina"
                  fill
                  sizes="(max-width: 768px) 100vw, 400px"
                  className="object-cover"
                />
              </div>
              <div className="flex-1 space-y-8 text-center md:text-left">
                <span className="text-5xl md:text-6xl font-serif text-brand-fresa/30 block tracking-tighter">Hoy</span>
                <h2 className="text-3xl md:text-4xl font-serif italic">RecetaDolce Studio</h2>
                <p className="text-white/70 font-serif italic leading-loose text-lg">
                  Hoy somos una comunidad de miles, un estudio creativo donde el diseño y la gastronomía convergen para elevar el estándar de lo que significa cocinar en casa. Nuestra misión sigue siendo la misma: encontrar lo extraordinario en lo cotidiano.
                </p>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* Signature Section */}
      <section className="py-40 px-6 text-center bg-cream-base">
        <div className="container mx-auto max-w-3xl">
          <div className="mb-16">
            <div className="fresa-dot mx-auto mb-10 scale-150" />
            <p className="text-3xl md:text-5xl font-serif text-ink italic leading-tight mb-12 tracking-tight">
              "La historia de RecetaDolce se escribe con cada bocado que disfrutas con los tuyos."
            </p>
            <div className="flex flex-col items-center">
               <span className="text-editorial text-brand-fresa">Equipo Editorial</span>
               <span className="text-xs uppercase tracking-[0.5em] text-gray-600 mt-4">Barcelona · RecetaDolce Studio</span>
            </div>
          </div>
          <Link 
            href="/"
            className="group inline-flex items-center space-x-6 text-brand-fresa font-serif italic text-2xl hover:opacity-70 transition-all pb-2"
          >
            <span>Explorar nuestras creaciones</span>
            <span className="text-3xl transition-transform group-hover:translate-x-2">→</span>
          </Link>
        </div>
      </section>
    </main>
  );
}
