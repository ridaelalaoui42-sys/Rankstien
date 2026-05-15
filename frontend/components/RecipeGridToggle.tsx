
'use client';

import React, { useState } from 'react';

interface RecipeGridToggleProps {
  children: React.ReactNode;
}

export default function RecipeGridToggle({ children }: RecipeGridToggleProps) {
  const [showAll, setShowAll] = useState(false);

  return (
    <>
      <div className={showAll ? 'contents' : 'hidden'}>
        {children}
      </div>

      <div className="flex justify-center mt-12 w-full col-span-full">
        <button
          onClick={() => setShowAll(!showAll)}
          className="px-12 py-4 bg-white border-2 border-brand-fresa/10 text-brand-fresa rounded-full text-sm font-bold uppercase tracking-[0.3em] hover:bg-brand-fresa hover:text-white transition-all duration-500 shadow-sm"
        >
          {showAll ? 'Ver Menos' : 'Ver Más Recetas'}
        </button>
      </div>
    </>
  );
}
