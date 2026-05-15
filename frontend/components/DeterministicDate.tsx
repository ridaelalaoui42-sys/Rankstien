'use client';

import { useState, useEffect } from 'react';

interface DeterministicDateProps {
  date: string | Date;
  className?: string;
  options?: Intl.DateTimeFormatOptions;
  locale?: string;
}

export default function DeterministicDate({ 
  date, 
  className = "", 
  options = { day: 'numeric', month: 'long', year: 'numeric' },
  locale = 'es-ES'
}: DeterministicDateProps) {
  const [formattedDate, setFormattedDate] = useState<string>("");

  useEffect(() => {
    const d = new Date(date);
    setFormattedDate(d.toLocaleDateString(locale, options));
  }, [date, locale, options]);

  // Return an empty span with the same font properties to avoid layout shift,
  // or a fallback if you prefer. Using a space-holder is safer for hydration.
  return <span className={className}>{formattedDate}</span>;
}
