
'use client';

import { useState, useEffect } from 'react';
import Image, { ImageProps } from 'next/image';

const DEFAULT_FALLBACK = 'https://res.cloudinary.com/dlopg0jmq/image/upload/v1777282752/RecetaDolce/mediterranean_ingredients_fallback.jpg';

interface SafeImageProps extends Omit<ImageProps, 'onError' | 'src'> {
  src?: string | null;
  fallbackSrc?: string;
  fetchPriority?: 'high' | 'low' | 'auto';
}

export default function SafeImage({ src, fallbackSrc = DEFAULT_FALLBACK, alt, fetchPriority, ...props }: SafeImageProps) {
  const [imgSrc, setImgSrc] = useState<string | null | undefined>(src || fallbackSrc);

  // Sync state if src changes
  useEffect(() => {
    setImgSrc(src || fallbackSrc);
  }, [src, fallbackSrc]);

  // Basic URL validation to prevent "Invalid URL" crash
  const getValidSrc = (source: string | null | undefined) => {
    if (!source || typeof source !== 'string' || source.trim() === '') return fallbackSrc;
    const value = source.trim();
    if (value === 'PLACEHOLDER') return fallbackSrc;
    if (value.startsWith('/') || value.startsWith('data:image/')) return value;
    if (/^https?:\/\//i.test(value)) return value;
    return fallbackSrc;
  };

  const finalSrc = getValidSrc(imgSrc);

  return (
    <Image
      {...props}
      src={finalSrc}
      alt={alt}
      fetchPriority={fetchPriority}
      onError={() => setImgSrc(fallbackSrc)}
    />
  );
}
