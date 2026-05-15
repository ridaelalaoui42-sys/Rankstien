import { FaHandsWash, FaTemperatureHigh, FaBoxOpen, FaInfoCircle } from 'react-icons/fa';

export const metadata = {
  title: 'Guía de Higiene Profesional | RecetaDolce',
  description: 'Protocolos de higiene y manipulación de alimentos para garantizar la seguridad en tu cocina.',
  alternates: {
    canonical: 'https://RecetaDolce.com/guia-higiene',
  },
};

export default function HygieneGuidePage() {
  return (
    <div className="bg-cream-base min-h-screen pt-24 pb-20">
      <div className="max-w-4xl mx-auto px-6">
        <div className="text-center mb-16">
          <h1 className="text-5xl md:text-6xl font-serif text-ink italic mb-6">Guía de Higiene</h1>
          <p className="text-gray-600 font-serif italic text-xl">Protocolos profesionales adaptados al hogar.</p>
        </div>

        <div className="space-y-12">
          <section className="bg-white p-10 rounded-[2.5rem] border border-brand-fresa/5 shadow-sm">
            <div className="flex items-center space-x-4 mb-6">
              <FaHandsWash className="text-brand-fresa text-3xl" />
              <h2 className="text-2xl font-serif italic text-ink">Lavado y Desinfección</h2>
            </div>
            <p className="text-gray-600 leading-relaxed mb-6">
              El primer paso de cualquier receta exitosa es la higiene personal y del entorno. Recomendamos el lavado de manos durante al menos 20 segundos con jabón neutro antes y después de manipular alimentos crudos.
            </p>
            <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <li className="flex items-start space-x-3 text-sm text-gray-600">
                <span className="text-brand-fresa mt-1">•</span>
                <span>Desinfección de vegetales con productos aptos para uso alimentario.</span>
              </li>
              <li className="flex items-start space-x-3 text-sm text-gray-600">
                <span className="text-brand-fresa mt-1">•</span>
                <span>Uso de tablas diferenciadas para carnes y verduras (sistema de colores).</span>
              </li>
            </ul>
          </section>

          <section className="bg-white p-10 rounded-[2.5rem] border border-brand-fresa/5 shadow-sm">
            <div className="flex items-center space-x-4 mb-6">
              <FaTemperatureHigh className="text-brand-fresa text-3xl" />
              <h2 className="text-2xl font-serif italic text-ink">Cadena de Frío</h2>
            </div>
            <p className="text-gray-600 leading-relaxed mb-6">
              Mantener los alimentos fuera de la "zona de peligro" (entre 5°C y 65°C) es crucial para evitar el crecimiento bacteriano.
            </p>
            <div className="p-6 bg-cream-soft/30 rounded-2xl border border-brand-fresa/5">
              <h4 className="font-bold text-ink mb-2 flex items-center">
                <FaInfoCircle className="mr-2 text-brand-fresa" /> Regla de las 2 Horas
              </h4>
              <p className="text-sm text-gray-600 italic">
                Nunca deje alimentos perecederos fuera del refrigerador por más de dos horas (una hora si la temperatura ambiente supera los 30°C).
              </p>
            </div>
          </section>

          <section className="bg-white p-10 rounded-[2.5rem] border border-brand-fresa/5 shadow-sm">
            <div className="flex items-center space-x-4 mb-6">
              <FaBoxOpen className="text-brand-fresa text-3xl" />
              <h2 className="text-2xl font-serif italic text-ink">Almacenamiento Inteligente</h2>
            </div>
            <p className="text-gray-600 leading-relaxed">
              Utilice recipientes herméticos de vidrio para evitar la transferencia de olores y garantizar la durabilidad. Etiquete siempre con la fecha de elaboración siguiendo el principio FIFO (First In, First Out).
            </p>
          </section>
        </div>

        {/* Technical References */}
        <div className="mt-16 pt-12 border-t border-brand-fresa/10">
          <h3 className="text-xs font-bold uppercase tracking-[0.4em] text-ink/40 mb-8 text-center">Referencias Técnicas</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <a 
              href="https://www.aesan.gob.es/AECOSAN/web/seguridad_alimentaria/detalle/legislacion_higiene_alimentos.htm" 
              target="_blank" 
              rel="nofollow noreferrer"
              className="bg-cream-soft/20 p-6 rounded-2xl border border-brand-fresa/5 hover:bg-brand-fresa/[0.02] transition-colors block"
            >
              <h4 className="text-xs font-bold text-ink mb-2 uppercase flex items-center justify-between">
                AESAN - Higiene en el Hogar
                <span className="text-[8px] text-brand-fresa px-2 py-0.5 border border-brand-fresa/20 rounded-full">OFICIAL</span>
              </h4>
              <p className="text-[10px] text-gray-600 italic leading-relaxed">
                Nuestros protocolos de lavado se basan en las recomendaciones de la Agencia Española de Seguridad Alimentaria para prevenir riesgos biológicos.
              </p>
            </a>
            <a 
              href="https://www.boe.es/buscar/act.php?id=BOE-A-2011-11604" 
              target="_blank" 
              rel="nofollow noreferrer"
              className="bg-cream-soft/20 p-6 rounded-2xl border border-brand-fresa/5 hover:bg-brand-fresa/[0.02] transition-colors block"
            >
              <h4 className="text-xs font-bold text-ink mb-2 uppercase flex items-center justify-between">
                BOE - Ley 17/2011
                <span className="text-[8px] text-brand-fresa px-2 py-0.5 border border-brand-fresa/20 rounded-full">LEGISLACIÓN</span>
              </h4>
              <p className="text-[10px] text-gray-600 italic leading-relaxed">
                Seguridad Alimentaria y Nutrición. Cumplimiento normativo para la divulgación de técnicas culinarias seguras en territorio nacional.
              </p>
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
