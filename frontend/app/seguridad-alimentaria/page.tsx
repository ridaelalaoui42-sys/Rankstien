import { FaShieldAlt, FaExclamationTriangle, FaCheckCircle, FaExternalLinkAlt } from 'react-icons/fa';
import Link from 'next/link';
import EEATSignals from '@/components/EEATSignals';

export const metadata = {
  title: 'Seguridad Alimentaria y Normativa (AESAN/BOE/EFSA)',
  description: 'Nuestro compromiso con la seguridad alimentaria en el hogar, siguiendo las directrices de la AESAN, EFSA y la Ley 17/2011 del BOE.',
  alternates: {
    canonical: 'https://RecetaDolce.com/seguridad-alimentaria',
  },
};

export default function FoodSafetyPage() {
  return (
    <div className="bg-cream-base min-h-screen pt-24 pb-20">
      <div className="max-w-4xl mx-auto px-6">
        {/* Hero Section */}
        <div className="text-center mb-16">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-brand-fresa/10 rounded-full mb-6">
            <FaShieldAlt className="text-brand-fresa text-4xl" />
          </div>
          <h1 className="text-5xl md:text-6xl font-serif text-ink italic mb-6 tracking-tight">Seguridad Alimentaria</h1>
          <p className="text-xl text-gray-600 font-serif italic max-w-2xl mx-auto">
            "En RecetaDolce, la excelencia no solo está en el sabor, sino en la seguridad y el respeto por la normativa vigente."
          </p>
        </div>

        {/* Regulatory Framework */}
        <div className="bg-white rounded-[3rem] p-10 md:p-16 border border-brand-fresa/5 shadow-[0_30px_60px_rgba(189,30,45,0.03)] mb-12">
          <h2 className="text-3xl font-serif text-ink mb-8 italic">Marco Regulatorio</h2>
          <p className="text-gray-600 mb-8 leading-relaxed">
            Todas nuestras recetas y consejos de manipulación de alimentos se alinean con los estándares establecidos por las autoridades competentes en España y la Unión Europea para garantizar la protección de la salud de nuestros lectores.
          </p>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="p-8 bg-cream-soft/30 rounded-2xl border border-brand-fresa/5 hover:border-brand-fresa/20 transition-all duration-500 group">
              <h3 className="text-xl font-bold text-ink mb-4 flex items-center">
                <span className="w-8 h-8 bg-brand-fresa text-white rounded-full flex items-center justify-center text-xs mr-3">AESAN</span>
                Autoridad Nacional
              </h3>
              <p className="text-sm text-gray-600 mb-6 leading-relaxed">
                La Agencia Española de Seguridad Alimentaria y Nutrición es el pilar de la normativa de higiene y seguridad en España.
              </p>
              <a 
                href="https://www.aesan.gob.es/AECOSAN/web/seguridad_alimentaria/detalle/legislacion_higiene_alimentos.htm" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-xs font-bold uppercase tracking-widest text-brand-fresa flex items-center group-hover:translate-x-2 transition-transform"
              >
                Ver Guía Oficial <FaExternalLinkAlt className="ml-2 text-[10px]" />
              </a>
            </div>

            <div className="p-8 bg-cream-soft/30 rounded-2xl border border-brand-fresa/5 hover:border-brand-fresa/20 transition-all duration-500 group">
              <h3 className="text-xl font-bold text-ink mb-4 flex items-center">
                <span className="w-8 h-8 bg-brand-fresa text-white rounded-full flex items-center justify-center text-xs mr-3">EFSA</span>
                Autoridad Europea
              </h3>
              <p className="text-sm text-gray-600 mb-6 leading-relaxed">
                La European Food Safety Authority proporciona el asesoramiento científico que sustenta las normas de seguridad en toda la UE.
              </p>
              <a 
                href="https://www.efsa.europa.eu/es" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-xs font-bold uppercase tracking-widest text-brand-fresa flex items-center group-hover:translate-x-2 transition-transform"
              >
                Portal Científico <FaExternalLinkAlt className="ml-2 text-[10px]" />
              </a>
            </div>
          </div>
        </div>

        {/* Pillars Section */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
          <div className="bg-white p-8 rounded-3xl border border-brand-fresa/5 shadow-sm">
            <FaExclamationTriangle className="text-brand-fresa mb-4" size={24} />
            <h4 className="font-bold text-ink mb-2">Evitar Contaminación</h4>
            <p className="text-sm text-gray-600 leading-relaxed">Protocolos de lavado y separación siguiendo el <strong>Reglamento (CE) n.º 852/2004</strong>.</p>
          </div>
          <div className="bg-white p-8 rounded-3xl border border-brand-fresa/5 shadow-sm">
            <FaCheckCircle className="text-brand-fresa mb-4" size={24} />
            <h4 className="font-bold text-ink mb-2">Control Térmico</h4>
            <p className="text-sm text-gray-600 leading-relaxed">Temperaturas seguras de cocción basadas en el <strong>Real Decreto 1021/2022</strong>.</p>
          </div>
          <div className="bg-white p-8 rounded-3xl border border-brand-fresa/5 shadow-sm">
            <FaShieldAlt className="text-brand-fresa mb-4" size={24} />
            <h4 className="font-bold text-ink mb-2">Trazabilidad</h4>
            <p className="text-sm text-gray-600 leading-relaxed">Identificación de origen bajo los principios del <strong>Reglamento (CE) n.º 178/2002</strong>.</p>
          </div>
        </div>

        <EEATSignals />

        {/* Bottom CTA */}
        <div className="text-center border-t border-brand-fresa/10 pt-12">
          <p className="text-gray-600 font-serif italic mb-6">Nuestro compromiso con la transparencia y el rigor científico es total.</p>
          <Link href="/contact" className="inline-block px-10 py-4 bg-brand-fresa text-white rounded-full font-bold uppercase tracking-widest text-xs hover:bg-ink transition-colors shadow-xl shadow-brand-fresa/20 hover:shadow-ink/20">
            Contactar con Soporte Técnico
          </Link>
        </div>
      </div>
    </div>
  );
}
