'use client';

import { FaPrint } from 'react-icons/fa';

interface PrintLinkProps {
  className?: string;
}

export default function PrintLink({ className }: PrintLinkProps) {
  return (
    <button 
      onClick={() => window.print()}
      className={className || "px-6 py-3 border border-brand-fresa/20 text-brand-fresa text-sm font-bold uppercase tracking-widest rounded-sm hover:bg-brand-fresa/5 transition-all flex items-center gap-2"}
    >
      <FaPrint size={12} />
      IMPRIMIR
    </button>
  );
}
