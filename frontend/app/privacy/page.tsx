import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Política de Privacidad | RecetaDolce - Transparencia Editorial',
  description: 'Conozca cómo RecetaDolce protege su privacidad y gestiona sus datos con la máxima transparencia y rigor editorial.',
  alternates: {
    canonical: 'https://RecetaDolce.com/privacy',
  },
};

const LAST_UPDATED = '22 de abril de 2025';

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-cream-base pb-32">
      {/* Legal Header */}
      <section className="relative pt-32 pb-16 text-center border-b border-cream-dark/50">
        <div className="absolute inset-0 bg-brand-fresa/5 -z-10 blur-3xl opacity-10" />
        <span className="text-editorial mb-4 block">Transparencia</span>
        <h1 className="text-5xl md:text-6xl font-serif text-ink mb-6 italic">Privacidad & Datos</h1>
        <div className="w-16 h-1 bg-brand-fresa mx-auto mb-6" />
        <p className="text-gray-600 font-serif italic text-sm">Última actualización: {LAST_UPDATED}</p>
      </section>

      <section className="container mx-auto px-6 py-20 max-w-4xl">
        <div className="bg-white p-12 md:p-20 rounded-[4rem] card-shadow border border-cream-dark prose-editorial">
          
          <div className="space-y-12">
            <section>
              <h2 className="text-3xl font-serif text-ink mb-6">1. Responsabilidad Editorial</h2>
              <p>
                <strong>RecetaDolce</strong> (en adelante, «la editorial») actúa como responsable del tratamiento de los datos personales recopilados a través de <em>RecetaDolce.com</em>. Nuestro compromiso con la excelencia culinaria se extiende a la protección de su privacidad.
              </p>
            </section>

            <section>
              <h2 className="text-3xl font-serif text-ink mb-6">2. Recolección de Datos</h2>
              <p>En nuestra búsqueda de ofrecer contenido personalizado, recopilamos:</p>
              <ul className="list-disc pl-6 space-y-4 text-gray-600">
                <li><strong>Identificación Digital:</strong> Correo electrónico y nombre para suscripciones al Magazine Genial.</li>
                <li><strong>Métricas de Experiencia:</strong> Datos de navegación anonimizados para optimizar la fluidez visual de nuestra interfaz.</li>
                <li><strong>Interacciones Culiniarias:</strong> Preferencias de búsqueda y recetas guardadas (para usuarios registrados).</li>
              </ul>
            </section>

            <section>
              <h2 className="text-3xl font-serif text-ink mb-6">3. Finalidad del Tratamiento</h2>
              <p>Sus datos se utilizan exclusivamente para:</p>
              <ul className="list-disc pl-6 space-y-4 text-gray-600">
                <li>Distribución de nuestro Magazine Editorial semanal.</li>
                <li>Atención personalizada de consultas a través de nuestros canales oficiales.</li>
                <li>Mejora continua de la estética y usabilidad del sitio.</li>
              </ul>
            </section>

            <section className="pull-quote">
              "Tratamos sus datos con el mismo respeto con el que tratamos una receta familiar centenaria: con cuidado, integridad y absoluta discreción."
            </section>

            <section>
              <h2 className="text-3xl font-serif text-ink mb-6">4. Sus Derechos</h2>
              <p>
                Bajo el marco del RGPD, usted mantiene el control absoluto sobre su información. Puede solicitar el acceso, rectificación o supresión de sus datos en cualquier momento enviando una comunicación formal a nuestra oficina digital.
              </p>
              <div className="mt-8 p-6 bg-cream-dark/30 rounded-3xl border border-cream-dark">
                <p className="text-sm font-bold text-ink mb-2">Contacto de Privacidad:</p>
                <a href="mailto:ridaelalaoui42@gmail.com" className="text-brand-red font-serif italic hover:text-brand-fresa transition-colors">
                  ridaelalaoui42@gmail.com
                </a>
              </div>
            </section>

            <section>
              <h2 className="text-3xl font-serif text-ink mb-6">5. Seguridad de Grado Editorial</h2>
              <p>
                Implementamos protocolos de cifrado TLS/SSL de última generación y medidas técnicas robustas para garantizar que su experiencia en RecetaDolce sea no solo deliciosa, sino también segura.
              </p>
            </section>
          </div>

          <div className="mt-20 pt-10 border-t border-cream-dark text-center">
            <p className="text-xs text-gray-600 font-serif italic">
              RecetaDolce Editorial © 2025 | Todos los derechos reservados.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
