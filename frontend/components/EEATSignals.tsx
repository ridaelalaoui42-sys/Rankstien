import { FaShieldAlt, FaCheckCircle, FaBalanceScale, FaBook } from 'react-icons/fa';

export default function EEATSignals() {
  const sources = [
    {
      id: "AESAN",
      title: "Agencia Española de Seguridad Alimentaria y Nutrición",
      type: "Primary Authority",
      category: "Government/Regulatory",
      link: "https://www.aesan.gob.es/AECOSAN/web/seguridad_alimentaria/detalle/legislacion_higiene_alimentos.htm",
      description: "Provides official regulatory framework for food hygiene and microbiological criteria applicable to food products in Spain.",
      usage: "Food safety guidelines for home cooking, proper handling of raw ingredients, microbiological safety standards."
    },
    {
      id: "BOE",
      title: "Boletín Oficial del Estado (BOE) - Ley 17/2011",
      type: "Primary Authority",
      category: "Government/Regulatory",
      link: "https://www.boe.es/buscar/act.php?id=BOE-A-2011-11604",
      description: "The legal foundation for food safety and nutrition rights in Spain, ensuring a high level of protection for consumers.",
      usage: "Defining food safety rights, legal nutrition standards, consumer protection framework."
    },
    {
      id: "EFSA",
      title: "European Food Safety Authority (EFSA)",
      type: "Scientific Authority",
      category: "European Union Agency",
      link: "https://www.efsa.europa.eu/es",
      description: "Independent scientific advice on existing and emerging risks associated with the food chain in Europe.",
      usage: "Scientific risk assessment, safety of food additives, emerging food safety trends."
    },
    {
      id: "CODEX",
      title: "Codex Alimentarius (WHO/FAO)",
      type: "International Standard",
      category: "Global Standards",
      link: "https://www.fao.org/fao-who-codexalimentarius/home/es/",
      description: "International food standards, guidelines, and codes of practice to contribute to the safety, quality, and fairness of the international food trade.",
      usage: "International labeling standards, global methods of analysis and sampling."
    }
  ];

  return (
    <section className="bg-cream-soft/30 border border-brand-fresa/10 rounded-[2.5rem] p-8 md:p-12 mb-16 relative overflow-hidden">
      <div className="absolute top-0 right-0 w-64 h-64 bg-brand-fresa/[0.02] rounded-full -mr-32 -mt-32 blur-3xl" />
      
      <div className="relative z-10">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-10 pb-8 border-b border-brand-fresa/10">
          <div>
            <h3 className="text-2xl font-serif text-ink italic mb-2">Compromiso de Autoridad (E-E-A-T)</h3>
            <p className="text-xs font-bold uppercase tracking-[0.3em] text-gray-500">Fuentes Verificadas y Normativa Vigente</p>
          </div>
          <div className="flex gap-4">
             <div className="flex flex-col items-center">
                <div className="w-10 h-10 bg-brand-fresa/10 rounded-full flex items-center justify-center text-brand-fresa mb-2">
                   <FaShieldAlt size={18} />
                </div>
                <span className="text-[8px] font-bold uppercase tracking-tighter text-ink">Seguridad</span>
             </div>
             <div className="flex flex-col items-center">
                <div className="w-10 h-10 bg-brand-fresa/10 rounded-full flex items-center justify-center text-brand-fresa mb-2">
                   <FaBalanceScale size={18} />
                </div>
                <span className="text-[8px] font-bold uppercase tracking-tighter text-ink">Legalidad</span>
             </div>
             <div className="flex flex-col items-center">
                <div className="w-10 h-10 bg-brand-fresa/10 rounded-full flex items-center justify-center text-brand-fresa mb-2">
                   <FaBook size={18} />
                </div>
                <span className="text-[8px] font-bold uppercase tracking-tighter text-ink">Ciencia</span>
             </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {sources.map((source) => (
            <div key={source.id} className="bg-white/80 backdrop-blur-sm p-6 rounded-2xl border border-brand-fresa/5 hover:border-brand-fresa/20 transition-all group">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <span className="bg-brand-fresa text-white text-[10px] font-black px-2 py-1 rounded uppercase tracking-tighter">
                    {source.id}
                  </span>
                  <h4 className="font-bold text-ink text-sm group-hover:text-brand-fresa transition-colors">{source.title}</h4>
                </div>
                <a 
                  href={source.link} 
                  target="_blank" 
                  rel="nofollow noopener noreferrer"
                  className="text-brand-fresa opacity-40 hover:opacity-100 transition-opacity"
                  aria-label={`Visitar fuente oficial de ${source.id}`}
                >
                  <FaCheckCircle size={14} />
                </a>
              </div>
              <p className="text-xs text-gray-600 leading-relaxed mb-4 italic">
                {source.description}
              </p>
              <div className="pt-4 border-t border-dashed border-gray-100 mt-auto">
                <p className="text-[10px] text-gray-400">
                  <span className="font-bold text-gray-600 uppercase tracking-tighter mr-2">Aplicación en RecetaDolce:</span>
                  {source.usage}
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-10 text-center">
           <p className="text-[10px] text-gray-400 font-serif italic">
              "La integridad de nuestra información culinaria se basa en la validación constante de fuentes oficiales de seguridad y nutrición."
           </p>
        </div>
      </div>
    </section>
  );
}
