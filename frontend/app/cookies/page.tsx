import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Política de Cookies | RecetaDolce',
  description: 'Información detallada sobre el uso de cookies en RecetaDolce Studio.',
  alternates: {
    canonical: 'https://RecetaDolce.com/cookies',
  },
};

export default function CookiesPage() {
  return (
    <main className="min-h-screen bg-cream-base pt-40 pb-32">
      <div className="container mx-auto px-6">
        <div className="max-w-4xl mx-auto">
          <header className="text-center mb-24">
            <span className="text-editorial text-brand-fresa mb-4 block">Transparencia Editorial</span>
            <h1 className="text-6xl md:text-7xl font-serif text-ink mb-8">Política de Cookies</h1>
            <div className="w-24 h-px bg-brand-fresa/20 mx-auto" />
          </header>

          <div className="bg-white rounded-[3rem] p-12 md:p-20 shadow-premium border border-brand-fresa/5 prose-editorial">
            <section className="mb-16">
              <h2 className="text-3xl font-serif text-ink mb-8 italic">1. ¿Qué son las cookies?</h2>
              <p className="text-gray-600 leading-loose mb-6">
                En RecetaDolce, utilizamos cookies y tecnologías similares para mejorar su experiencia culinaria en nuestro santuario digital. Una cookie es un pequeño archivo de texto que se almacena en su navegador cuando visita nuestro sitio.
              </p>
            </section>

            <section className="mb-16">
              <h2 className="text-3xl font-serif text-ink mb-8 italic">2. Tipos de cookies que utilizamos</h2>
              <div className="space-y-8">
                <div className="p-8 bg-brand-fresa/5 rounded-2xl border border-brand-fresa/10">
                  <h4 className="text-sm font-bold uppercase tracking-widest text-brand-fresa mb-4">Cookies Necesarias</h4>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    Esenciales para que el sitio funcione correctamente. Permiten la navegación y el acceso a áreas seguras como el Portal de Administración.
                  </p>
                </div>
                <div className="p-8 bg-brand-fresa/5 rounded-2xl border border-brand-fresa/10">
                  <h4 className="text-sm font-bold uppercase tracking-widest text-brand-fresa mb-4">Cookies de Rendimiento</h4>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    Nos ayudan a entender cómo interactúan los visitantes con nuestras recetas, permitiéndonos optimizar la velocidad y el diseño del sitio.
                  </p>
                </div>
                <div className="p-8 bg-brand-fresa/5 rounded-2xl border border-brand-fresa/10">
                  <h4 className="text-sm font-bold uppercase tracking-widest text-brand-fresa mb-4">Cookies de Personalización</h4>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    Permiten recordar sus preferencias, como el idioma o la región, para ofrecerle una experiencia más íntima y personalizada.
                  </p>
                </div>
              </div>
            </section>

            <section className="mb-16">
              <h2 className="text-3xl font-serif text-ink mb-8 italic">3. Control de cookies</h2>
              <p className="text-gray-600 leading-loose mb-6">
                Usted tiene el derecho de aceptar o rechazar las cookies. La mayoría de los navegadores web aceptan cookies automáticamente, pero generalmente puede modificar la configuración de su navegador para rechazarlas si lo prefiere. Tenga en cuenta que esto puede afectar la funcionalidad de algunas secciones de RecetaDolce.
              </p>
            </section>

            <section>
              <h2 className="text-3xl font-serif text-ink mb-8 italic">4. Actualizaciones</h2>
              <p className="text-gray-600 leading-loose">
                Esta política puede ser actualizada periódicamente para reflejar cambios en nuestras prácticas o por razones legales. Le recomendamos revisarla regularmente.
              </p>
              <p className="text-sm text-brand-fresa mt-12 font-bold uppercase tracking-widest">
                Última actualización: Abril 2026
              </p>
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
