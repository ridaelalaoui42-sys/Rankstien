
'use client';

import { useEffect } from 'react';
import Link from 'next/link';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Runtime error in Article Page:', error);
  }, [error]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-8 text-center bg-cream-light">
      <div className="max-w-md">
        <h2 className="text-4xl font-serif italic text-ink mb-6">Algo no ha salido bien</h2>
        <p className="text-lg text-gray-600 mb-10 leading-relaxed">
          Lo sentimos, ha ocurrido un error inesperado al cargar esta receta. Nuestro equipo técnico ha sido notificado.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <button
            onClick={() => reset()}
            className="px-8 py-4 bg-ink text-white rounded-full text-xs font-bold uppercase tracking-widest hover:bg-brand-fresa transition-colors shadow-lg"
          >
            Intentar de nuevo
          </button>
          <Link
            href="/"
            className="px-8 py-4 bg-white text-ink border border-gray-200 rounded-full text-xs font-bold uppercase tracking-widest hover:bg-gray-50 transition-colors shadow-sm"
          >
            Volver al inicio
          </Link>
        </div>
        {process.env.NODE_ENV === 'development' && (
          <div className="mt-12 p-4 bg-red-50 text-red-800 text-left rounded-lg text-sm font-mono overflow-auto max-h-40 border border-red-100">
            {error.message}
          </div>
        )}
      </div>
    </div>
  );
}
