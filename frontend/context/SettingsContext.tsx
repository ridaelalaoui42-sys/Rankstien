'use client';

import React, { createContext, useContext, ReactNode } from 'react';
import { Settings } from '@/types';

const SettingsContext = createContext<Settings | null>(null);

export function SettingsProvider({ 
  children, 
  settings 
}: { 
  children: ReactNode; 
  settings: Settings | null 
}) {
  return (
    <SettingsContext.Provider value={settings}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  return useContext(SettingsContext);
}
