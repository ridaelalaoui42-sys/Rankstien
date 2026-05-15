import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Términos y Condiciones | RecetaDolce',
  description: 'Condiciones de uso y términos legales de RecetaDolce Studio.',
  alternates: {
    canonical: 'https://RecetaDolce.com/terms',
  },
};

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-cream-base pt-40 pb-32">
      <div className="container mx-auto px-6">
        <div className="max-w-4xl mx-auto">
          <header className="text-center mb-24">
            <span className="text-editorial text-brand-fresa mb-4 block">Marco Legal</span>
            <h1 className="text-6xl md:text-7xl font-serif text-ink mb-8">Términos de Uso</h1>
            <div className="w-24 h-px bg-brand-fresa/20 mx-auto" />
          </header>

          <div className="bg-white rounded-[3rem] p-12 md:p-20 shadow-premium border border-brand-fresa/5 prose-editorial">
            <section className="mb-16">
              <h2 className="text-3xl font-serif text-ink mb-8 italic">1. Aceptación de los Términos</h2>
              <p className="text-gray-600 leading-loose mb-6">
                Al acceder a RecetaDolce, usted acepta cumplir con estos términos de servicio, todas las leyes y regulaciones aplicables, y acepta que es responsable del cumplimiento de cualquier ley local aplicable.
              </p>
            </section>

            <section className="mb-16">
              <h2 className="text-3xl font-serif text-ink mb-8 italic">2. Propiedad Intelectual</h2>
              <p className="text-gray-600 leading-loose mb-6">
                Todo el contenido editorial, fotografías, recetas y diseños presentados en RecetaDolce son propiedad intelectual de RecetaDolce Studio, a menos que se indique lo contrario. Queda prohibida la reproducción total o parcial sin consentimiento expreso por escrito.
              </p>
            </section>

            <section className="mb-16">
              <h2 className="text-3xl font-serif text-ink mb-8 italic">3. Limitación de Responsabilidad</h2>
              <p className="text-gray-600 leading-loose mb-6">
                RecetaDolce proporciona información culinaria solo con fines educativos. No nos hacemos responsables de alergias, intolerancias o resultados insatisfactorios en la preparación de las recetas. Recomendamos siempre seguir las prácticas básicas de seguridad alimentaria.
              </p>
            </section>

            <section className="mb-16">
              <h2 className="text-3xl font-serif text-ink mb-8 italic">4. Modificaciones</h2>
              <p className="text-gray-600 leading-loose mb-6">
                RecetaDolce puede revisar estos términos de servicio para su sitio web en cualquier momento sin previo aviso. Al utilizar este sitio web, usted acepta estar vinculado por la versión actual de estos términos de servicio.
              </p>
            </section>

            <section>
              <h2 className="text-3xl font-serif text-ink mb-8 italic">5. Ley Aplicable</h2>
              <p className="text-gray-600 leading-loose">
                Cualquier reclamación relacionada con el sitio web de RecetaDolce se regirá por las leyes del Reino de España, sin consideración a sus disposiciones sobre conflictos de leyes.
              </p>
              <p className="text-sm text-brand-fresa mt-12 font-bold uppercase tracking-widest">
                Última revisión: Abril 2026
              </p>
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
