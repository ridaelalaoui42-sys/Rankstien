'use client';
import { useRouter } from 'next/navigation';
import Cookies from 'js-cookie';

export default function LogoutButton() {
  const router = useRouter();

  const handleLogout = async () => {
    if (!confirm('¿Cerrar sesión de administración?')) return;
    
    try {
      const res = await fetch('/api/admin/auth', { method: 'DELETE' });
      if (res.ok) {
        // Clear all admin indicators
        localStorage.removeItem('rd_admin');
        Cookies.remove('rd_admin');
        
        router.push('/');
        router.refresh();
      }
    } catch (error) {
      console.error('Logout error:', error);
    }
  };

  return (
    <button
      onClick={handleLogout}
      className="text-sm font-bold uppercase tracking-[0.2em] text-gray-600 hover:text-brand-red transition-colors"
    >
      Cerrar Sesión
    </button>
  );
}
