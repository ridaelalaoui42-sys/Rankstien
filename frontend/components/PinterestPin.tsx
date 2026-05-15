'use client';

import React from 'react';

interface PinterestPinProps {
  pinId?: string;
}

export default function PinterestPin({ pinId }: PinterestPinProps) {
  if (!pinId) return null;

  return (
    <div className="relative w-full max-w-xl mx-auto my-16 print:hidden">
      {/* Section header */}
      <div className="text-center mb-6">
        <span className="inline-block px-4 py-1.5 text-xs font-bold uppercase tracking-[0.35em] text-brand-fresa/70 border border-brand-fresa/15 rounded-full bg-brand-fresa/5">
          Guarda esta receta
        </span>
      </div>

      {/* Pin container — responsive, centered, minimal chrome */}
      <div className="flex justify-center">
        <div className="relative group">
          {/* Subtle glow on hover */}
          <div className="absolute -inset-3 bg-brand-fresa/5 rounded-3xl blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-700 pointer-events-none" />
          
          <div className="relative bg-white rounded-2xl shadow-lg border border-gray-100 overflow-hidden transition-shadow duration-500 group-hover:shadow-2xl">
            <iframe
              src={`https://assets.pinterest.com/ext/embed.html?id=${pinId}`}
              width="345"
              height="550"
              frameBorder="0"
              scrolling="no"
              loading="lazy"
              title="Pin de Pinterest — RecetaDolce"
              className="block"
              sandbox="allow-scripts allow-popups allow-same-origin"
              style={{ maxWidth: '100%' }}
            />
          </div>
        </div>
      </div>

      {/* CTA link to Pinterest */}
      <div className="mt-5 text-center">
        <a
          href={`https://www.pinterest.com/pin/${pinId}/`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-sm font-medium text-gray-500 hover:text-brand-fresa transition-colors duration-300"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.373 0 0 5.373 0 12c0 5.084 3.163 9.426 7.627 11.174-.105-.949-.2-2.405.042-3.441.218-.937 1.407-5.965 1.407-5.965s-.359-.719-.359-1.782c0-1.668.967-2.914 2.171-2.914 1.023 0 1.518.769 1.518 1.69 0 1.029-.655 2.568-.994 3.995-.283 1.194.599 2.169 1.777 2.169 2.133 0 3.772-2.249 3.772-5.495 0-2.873-2.064-4.882-5.012-4.882-3.414 0-5.418 2.561-5.418 5.207 0 1.031.397 2.138.893 2.738a.36.36 0 01.083.345l-.333 1.36c-.053.22-.174.267-.402.161-1.499-.698-2.436-2.889-2.436-4.649 0-3.785 2.75-7.262 7.929-7.262 4.163 0 7.398 2.967 7.398 6.931 0 4.136-2.607 7.464-6.227 7.464-1.216 0-2.359-.632-2.75-1.378l-.748 2.853c-.271 1.043-1.002 2.35-1.492 3.146C9.57 23.812 10.763 24 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0z"/>
          </svg>
          Ver en Pinterest
        </a>
      </div>
    </div>
  );
}
