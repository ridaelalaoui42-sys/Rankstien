import { Metadata } from 'next';
import ContactForm from '@/components/ContactForm';
import { getSettings } from '@/lib/settings';

export const metadata: Metadata = {
  title: 'Contacto | RecetaDolce - Nuestra Mesa está Abierta',
  description: 'Ponte en contacto con el equipo editorial de RecetaDolce. Colaboraciones, prensa o simplemente una charla sobre el buen comer.',
  alternates: {
    canonical: 'https://RecetaDolce.com/contact',
  },
};

export default async function ContactPage() {
  const settings = await getSettings();
  const contactEmail = settings?.contact_email || 'ridaelalaoui42@gmail.com';

  const socialLinks = [
    { label: 'Instagram', handle: '@RecetaDolce', url: settings?.instagram_url || 'https://instagram.com' },
    { label: 'Pinterest', handle: 'RecetaDolce', url: settings?.pinterest_url || 'https://pinterest.com' },
    { label: 'TikTok', handle: '@RecetaDolce', url: settings?.tiktok_url || 'https://tiktok.com' },
    { label: 'YouTube', handle: 'RecetaDolce', url: settings?.youtube_url || 'https://youtube.com' },
  ].filter(s => s.url);

  return (
    <main className="min-h-screen bg-cream-base pb-32 selection:bg-brand-fresa/10">
      {/* Editorial Header */}
      <section className="relative pt-40 pb-24 text-center">
        <div className="absolute top-0 left-0 w-full h-full bg-brand-fresa/[0.02] -z-10" />
        <div className="container mx-auto px-6 animate-fade-up">
          <span className="text-editorial mb-8 inline-block px-4 py-1 border-x border-brand-fresa/20">Canales de Comunicación</span>
          <h1 className="text-7xl md:text-[8rem] font-serif text-ink mb-10 italic leading-[0.85]">Escríbenos.</h1>
          <div className="w-32 h-px bg-brand-fresa/30 mx-auto mb-12" />
          <p className="text-2xl md:text-3xl font-serif italic text-gray-600 max-w-2xl mx-auto leading-relaxed">
            "Donde las palabras se encuentran con el sabor. Estamos aquí para escuchar su historia culinaria."
          </p>
        </div>
      </section>

      <section className="container mx-auto px-6 py-24 max-w-7xl">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-16 items-start">
          {/* Sidebar Info */}
          <div className="lg:col-span-5 space-y-12 animate-fade-up" style={{ animationDelay: '0.1s' }}>
            <div className="bg-white p-16 rounded-[4rem] shadow-[0_40px_80px_rgba(164,19,60,0.04)] border border-brand-fresa/5 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-32 h-32 bg-brand-fresa/[0.02] rounded-full translate-x-16 -translate-y-16" />
              <h2 className="text-4xl font-serif text-ink mb-12 italic">Atención Editorial</h2>
              
              <div className="space-y-16">
                <div className="group">
                  <p className="text-editorial mb-4">Correspondencia General</p>
                  <a 
                    href={`mailto:${contactEmail}`} 
                    className="text-3xl font-serif text-ink hover:text-brand-fresa transition-all duration-700 hover-fresa-line inline-block"
                  >
                    {contactEmail}
                  </a>
                </div>

                <div className="group">
                  <p className="text-editorial mb-4">Prensa & Alianzas</p>
                  <a 
                    href={`mailto:${contactEmail}`} 
                    className="text-3xl font-serif text-ink hover:text-brand-fresa transition-all duration-700 hover-fresa-line inline-block"
                  >
                    {contactEmail}
                  </a>
                </div>

                <div className="pt-8 border-t border-brand-fresa/5">
                  <p className="text-editorial mb-4">Plazos de Gracia</p>
                  <p className="text-gray-600 italic font-serif leading-relaxed text-lg">
                    Cada mensaje es leído con la pausa que merece un buen vino. Respondemos usualmente entre 48 y 72 horas laborales.
                  </p>
                </div>
              </div>
            </div>

            <div className="p-16 bg-brand-red rounded-[4rem] text-white shadow-2xl shadow-brand-red/20 relative overflow-hidden group">
              <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-br from-brand-fresa/20 to-transparent" />
              <h3 className="text-2xl font-serif mb-10 relative z-10">Pulso Social</h3>
              <div className="grid grid-cols-2 gap-12 relative z-10">
                {socialLinks.map((s) => (
                  <a key={s.label} href={s.url} target="_blank" rel="noopener noreferrer" className="block hover:translate-x-2 transition-transform duration-500">
                    <p className="text-sm uppercase tracking-[0.4em] text-white/50 mb-2">{s.label}</p>
                    <p className="font-serif italic text-xl group-hover:text-brand-fresa-light transition-colors">{s.handle}</p>
                  </a>
                ))}
              </div>
            </div>
          </div>

          {/* Contact Form */}
          <div className="lg:col-span-7 bg-white p-12 md:p-20 rounded-[4rem] shadow-[0_50px_100px_rgba(164,19,60,0.06)] border border-brand-fresa/5 relative animate-fade-up" style={{ animationDelay: '0.2s' }}>
            <div className="absolute top-12 right-12 text-8xl text-brand-fresa/[0.03] pointer-events-none font-serif select-none italic">Genial</div>
            <div className="relative">
              <span className="text-editorial mb-6 block">Envío Digital</span>
              <h2 className="text-5xl font-serif text-ink mb-12 italic">Buzón de Ideas</h2>
              <ContactForm />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
