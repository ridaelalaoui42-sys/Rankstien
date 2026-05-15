
'use client';

import { useState } from 'react';
import { FaFacebookF, FaWhatsapp, FaLink, FaCheck } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';

interface ShareMenuProps {
  title: string;
  slug: string;
}

export default function ShareMenu({ title, slug }: ShareMenuProps) {
  const [copied, setCopied] = useState(false);
  const shareUrl = `https://RecetaDolce.com/${slug}`;

  const copyToClipboard = () => {
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const shareLinks = [
    {
      name: 'X',
      icon: <FaXTwitter />,
      url: `https://twitter.com/intent/tweet?text=${encodeURIComponent(title)}&url=${encodeURIComponent(shareUrl)}`,
      color: 'hover:bg-black'
    },
    {
      name: 'Facebook',
      icon: <FaFacebookF />,
      url: `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}`,
      color: 'hover:bg-[#1877F2]'
    },
    {
      name: 'WhatsApp',
      icon: <FaWhatsapp />,
      url: `https://api.whatsapp.com/send?text=${encodeURIComponent(title + ' ' + shareUrl)}`,
      color: 'hover:bg-[#25D366]'
    }
  ];

  return (
    <>
      {/* Desktop Floating Bar */}
      <div className="fixed left-8 top-1/2 -translate-y-1/2 hidden xl:flex flex-col space-y-4 z-40 animate-fade-in">
        <div className="bg-white/80 backdrop-blur-md p-3 rounded-full border border-brand-fresa/10 shadow-xl flex flex-col space-y-4">
          {shareLinks.map((link) => (
            <a
              key={link.name}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className={`w-10 h-10 rounded-full flex items-center justify-center text-gray-600 ${link.color} hover:text-white transition-all duration-300 transform hover:scale-110`}
              title={`Compartir en ${link.name}`}
              aria-label={`Compartir en ${link.name}`}
            >
              {link.icon}
            </a>
          ))}
          <button
            onClick={copyToClipboard}
            className={`w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 transform hover:scale-110 ${
              copied ? 'bg-green-500 text-white' : 'text-gray-600 hover:bg-brand-fresa hover:text-white'
            }`}
            title="Copiar enlace"
            aria-label={copied ? "Enlace copiado" : "Copiar enlace al portapapeles"}
          >
            {copied ? <FaCheck /> : <FaLink />}
          </button>
        </div>
      </div>

      {/* Mobile Bottom Bar */}
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 xl:hidden z-40 animate-fade-up">
        <div className="bg-white/90 backdrop-blur-xl px-6 py-4 rounded-full border border-brand-fresa/10 shadow-2xl flex items-center space-x-6">
          <span className="text-sm font-bold uppercase tracking-widest text-brand-fresa border-r border-brand-fresa/10 pr-6">Compartir</span>
          {shareLinks.map((link) => (
            <a
              key={link.name}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-600 hover:text-brand-fresa transition-colors"
              aria-label={`Compartir en ${link.name}`}
            >
              {link.icon}
            </a>
          ))}
          <button
            onClick={copyToClipboard}
            className={`${copied ? 'text-green-500' : 'text-gray-600'}`}
            aria-label="Copiar enlace"
          >
            {copied ? <FaCheck /> : <FaLink />}
          </button>
        </div>
      </div>
    </>
  );
}
