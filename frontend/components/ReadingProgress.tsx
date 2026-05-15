
'use client';

import { useState, useEffect } from 'react';

export default function ReadingProgress() {
  const [completion, setCompletion] = useState(0);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    let ticking = false;

    const updateScrollCompletion = () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          const currentProgress = window.scrollY;
          const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
          if (scrollHeight > 0) {
            setCompletion(
              Number((currentProgress / scrollHeight).toFixed(2)) * 100
            );
          }
          ticking = false;
        });
        ticking = true;
      }
    };

    window.addEventListener('scroll', updateScrollCompletion, { passive: true });
    return () => window.removeEventListener('scroll', updateScrollCompletion);
  }, []);

  if (!mounted) return null;

  return (
    <div 
      className="fixed top-0 left-0 w-full h-1 z-[100]"
      role="progressbar"
      aria-label="Progreso de lectura"
      aria-valuenow={Math.round(completion)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div 
        className="h-full bg-brand-fresa transition-[width] duration-150 ease-out shadow-[0_0_10px_rgba(255,107,107,0.5)]"
        style={{ width: `${completion}%` }}
      />
    </div>
  );
}
