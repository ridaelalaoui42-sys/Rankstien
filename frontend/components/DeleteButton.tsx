'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function DeleteButton({ postId }: { postId: string }) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleDelete = async () => {
    if (!confirm('¿Eliminar esta receta permanentemente?')) return;
    setLoading(true);
    await fetch(`/api/admin/posts/${postId}`, { method: 'DELETE' });
    router.refresh();
    setLoading(false);
  };

  return (
    <button
      onClick={handleDelete}
      disabled={loading}
      className="text-red-600 font-bold text-xs hover:text-red-800 transition-colors disabled:opacity-50"
    >
      {loading ? '...' : 'Eliminar'}
    </button>
  );
}
