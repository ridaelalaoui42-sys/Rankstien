'use client';

import { useEffect, useRef } from 'react';
import { useSettings } from '@/context/SettingsContext';

declare global {
  interface Window {
    adsbygoogle?: unknown[];
  }
}

interface AdUnitProps {
  slot?: string;
  format?: 'auto' | 'fluid' | 'rectangle';
  style?: React.CSSProperties;
  className?: string;
  label?: string;
}

export default function AdUnit({ 
  slot, 
  format = 'auto', 
  style = { display: 'block' }, 
  className = '',
  label = 'Publicidad'
}: AdUnitProps) {
  const settings = useSettings();
  const adRef = useRef<HTMLModElement>(null);

  useEffect(() => {
    if (settings?.ads_enabled && settings?.adsense_client_id && slot) {
      try {
        (window.adsbygoogle = window.adsbygoogle || []).push({});
      } catch (err) {
        console.error('AdSense error:', err);
      }
    }
  }, [settings?.ads_enabled, settings?.adsense_client_id, slot]);

  if (!settings?.ads_enabled || !settings?.adsense_client_id || !slot) {
    // Show a placeholder in development or if ads are disabled
    return (
      <div className={`ad-placeholder flex flex-col items-center justify-center bg-gray-50 border border-dashed border-gray-200 rounded-lg min-h-[100px] my-8 p-4 ${className}`}>
        <span className="text-sm font-bold uppercase tracking-widest text-gray-300 mb-2">{label}</span>
        <div className="w-full h-20 bg-gray-100/50 rounded flex items-center justify-center">
          <span className="text-sm text-gray-600 italic">Espacio Publicitario</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`ad-container my-8 min-h-[280px] flex flex-col items-center justify-center overflow-hidden contain-layout ${className}`}>
      <span className="block text-sm font-bold uppercase tracking-widest text-gray-300 mb-2 text-center">{label}</span>
      <div className="w-full h-full flex items-center justify-center">
        <ins
          className="adsbygoogle"
          style={{ ...style, minWidth: '250px', minHeight: '250px' }}
          data-ad-client={settings.adsense_client_id}
          data-ad-slot={slot}
          data-ad-format={format}
          data-full-width-responsive="true"
          ref={adRef}
        />
      </div>
    </div>
  );
}
