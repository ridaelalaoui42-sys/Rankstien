
'use client';
import NewsletterForm from './NewsletterForm';

export default function NewsletterSection() {
  return (
    <section className="relative py-6 md:py-12 overflow-hidden bg-white border-y border-brand-fresa/10">
      {/* Decorative background - Hidden on extra small screens to prevent overlap */}
      <div className="absolute top-0 left-0 w-full h-full opacity-[0.02] md:opacity-[0.03] pointer-events-none select-none overflow-hidden">
        <div className="text-[10rem] md:text-[20rem] font-serif absolute -top-20 md:-top-40 -left-10 md:-left-20 text-brand-fresa rotate-12">Genial</div>
        <div className="text-[10rem] md:text-[20rem] font-serif absolute -bottom-20 md:-bottom-40 -right-10 md:-right-20 text-brand-fresa -rotate-12">Gourmet</div>
      </div>

      <div className="container mx-auto px-6 relative z-10">
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-12 md:gap-24 items-center">
          <div className="animate-fade-up">
            <span className="text-editorial text-brand-fresa mb-4 md:mb-6 block uppercase tracking-[0.6em] text-sm">Magazine RecetaDolce</span>
            <h2 className="text-3xl md:text-5xl lg:text-6xl font-serif text-ink mb-6 md:mb-8 leading-[0.95] tracking-tightest">
              Nuestra <br />
              <span className="text-fresa-gradient italic font-light">edición</span> <br />
              <span className="text-gray-600">semanal</span>
            </h2>
            <p className="text-lg md:text-xl text-gray-600 font-serif italic leading-relaxed mb-8 md:mb-12 max-w-lg border-l-2 border-brand-fresa/10 pl-6 md:pl-8">
              "Secretos de alta cocina y las historias detrás de los platos más emblemáticos de España, directos a tu bandeja de entrada."
            </p>
            
            <div className="flex items-center space-x-12 md:space-x-16">
              <div className="flex flex-col">
                <span className="text-2xl md:text-3xl font-serif text-ink tracking-tighter">5.2k</span>
                <span className="text-sm font-bold uppercase tracking-[0.3em] text-brand-fresa/40">Gourmets</span>
              </div>
              <div className="flex flex-col">
                <span className="text-2xl md:text-3xl font-serif text-ink tracking-tighter">100%</span>
                <span className="text-sm font-bold uppercase tracking-[0.3em] text-brand-fresa/40">Exclusivo</span>
              </div>
            </div>
          </div>

          <div className="bg-cream-base p-6 md:p-12 rounded-[2rem] md:rounded-[3rem] card-shadow border border-brand-fresa/5 animate-fade-up" style={{ animationDelay: '0.2s' }}>
            <div className="mb-8 md:mb-12">
              <h3 className="text-xl md:text-2xl font-serif text-ink mb-4">Suscripción Exclusiva</h3>
              <p className="text-sm text-gray-600 font-sans italic mb-8 md:mb-10">Ingresa tu correo para recibir nuestra guía de "Tapas de Autor" de regalo.</p>
              
              <ul className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-1 gap-4 md:gap-6 mb-10 md:mb-12">
                {[
                  'Acceso a Recetas Privadas',
                  'Masterclasses Mensuales',
                  'Guías en PDF de Temporada',
                  'Invitaciones a Eventos'
                ].map((item, i) => (
                  <li key={i} className="flex items-center space-x-3 md:space-x-4 text-xs md:text-sm font-bold uppercase tracking-widest text-ink">
                    <div className="w-5 h-5 md:w-6 md:h-6 rounded-full bg-brand-fresa/10 flex items-center justify-center text-brand-fresa shrink-0">
                      <svg className="w-2.5 h-2.5 md:w-3 md:h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <NewsletterForm />
          </div>
        </div>
      </div>
    </section>
  );
}
