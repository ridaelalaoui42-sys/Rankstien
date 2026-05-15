
import { FaUtensils, FaEye, FaComment, FaCheckCircle } from 'react-icons/fa';

const stats = [
  { label: 'RECETAS PUBLICADAS', value: '1.200+', icon: FaUtensils },
  { label: 'VISITAS MENSUALES', value: '2M+', icon: FaEye },
  { label: 'COMENTARIOS', value: '45K+', icon: FaComment },
  { label: 'CALIDAD GARANTIZADA', value: '100%', icon: FaCheckCircle },
];

export default function SocialStats() {
  return (
    <section className="py-8 bg-brand-fresa-deep text-white">
      <div className="container mx-auto px-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map((stat, idx) => (
            <div key={idx} className="flex flex-col items-center text-center">
              <stat.icon size={32} className="mb-4 text-brand-fresa-light opacity-80" />
              <div className="text-3xl md:text-4xl font-serif font-bold mb-1">{stat.value}</div>
              <div className="text-sm font-bold uppercase tracking-widest text-brand-fresa-light">
                {stat.label}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
