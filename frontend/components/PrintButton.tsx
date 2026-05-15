'use client';

import { FaPrint } from 'react-icons/fa';

export default function PrintButton() {
  return (
    <button
      onClick={() => window.print()}
      className="w-16 h-16 rounded-full border border-brand-fresa/10 flex items-center justify-center text-brand-fresa hover:bg-white transition-all duration-500 bg-white/50 backdrop-blur-sm"
      title="Imprimir Receta"
      aria-label="Imprimir Receta"
    >
      <FaPrint size={14} />
    </button>
  );
}
