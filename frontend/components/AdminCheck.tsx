'use client';

import { useEffect } from 'react';
import { useSearchParams } from 'next/navigation';

interface AdminCheckProps {
  onAdmin: () => void;
}

export default function AdminCheck({ onAdmin }: AdminCheckProps) {
  const searchParams = useSearchParams();
  
  useEffect(() => {
    if (searchParams && searchParams.get('admin') === 'true') {
      onAdmin();
    }
  }, [searchParams, onAdmin]);
  
  return null;
}
