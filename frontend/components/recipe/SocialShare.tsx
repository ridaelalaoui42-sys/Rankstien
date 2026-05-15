'use client';

import { Printer } from 'lucide-react';
import { FaFacebookF, FaWhatsapp } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';
import styles from '../../app/recetas/pollo-al-ajillo-facil/recipe.module.css';

interface SocialShareProps {
  url: string;
  title: string;
}

export default function SocialShare({ url, title }: SocialShareProps) {
  const encodedUrl = encodeURIComponent(url);
  const encodedTitle = encodeURIComponent(title);

  const shareLinks = {
    facebook: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`,
    twitter: `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedTitle}`,
    pinterest: `https://pinterest.com/pin/create/button/?url=${encodedUrl}&description=${encodedTitle}`,
    whatsapp: `https://api.whatsapp.com/send?text=${encodedTitle}%20${encodedUrl}`
  };

  return (
    <div className="flex items-center gap-4 py-6 border-y border-cream-dark my-8">
      <span className="text-editorial">Compartir Receta:</span>
      <div className="flex gap-2">
        <a 
          href={shareLinks.facebook} 
          target="_blank" 
          rel="noopener noreferrer"
          className="w-10 h-10 rounded-full bg-cream-soft flex items-center justify-center text-brand-fresa hover:bg-brand-fresa hover:text-white transition-all"
          aria-label="Compartir en Facebook"
        >
          <FaFacebookF size={18} />
        </a>
        <a 
          href={shareLinks.twitter} 
          target="_blank" 
          rel="noopener noreferrer"
          className="w-10 h-10 rounded-full bg-cream-soft flex items-center justify-center text-brand-fresa hover:bg-brand-fresa hover:text-white transition-all"
          aria-label="Compartir en X"
        >
          <FaXTwitter size={18} />
        </a>
        <button 
          onClick={() => window.print()}
          className="w-10 h-10 rounded-full bg-cream-soft flex items-center justify-center text-brand-fresa hover:bg-brand-fresa hover:text-white transition-all"
          aria-label="Imprimir receta"
        >
          <Printer size={18} />
        </button>
        <a 
          href={shareLinks.whatsapp} 
          target="_blank" 
          rel="noopener noreferrer"
          className="w-10 h-10 rounded-full bg-cream-soft flex items-center justify-center text-brand-fresa hover:bg-brand-fresa hover:text-white transition-all"
          aria-label="Compartir en WhatsApp"
        >
          <FaWhatsapp size={18} />
        </a>
      </div>
    </div>
  );
}
