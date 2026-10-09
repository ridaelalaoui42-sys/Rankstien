'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function AdminLoginPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    const res = await fetch('/api/admin/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });

    if (res.ok) {
      localStorage.setItem('rd_admin', 'true');
      window.location.href = '/admin';
    } else {
      const json = await res.json();
      setError(json.error || 'Error de autenticación');
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-12">
          <h1 className="text-3xl font-serif text-gray-900">
            Receta<span className="text-brand-red italic font-light">Genial</span>
          </h1>
          <p className="text-sm font-bold uppercase tracking-[0.4em] text-gray-600 mt-3">
            Panel de Administración
          </p>
        </div>

        <div className="bg-white border border-gray-100 p-10">
          <h2 className="text-xl font-serif text-gray-900 mb-8 text-center">Acceso privado</h2>

          <form onSubmit={handleLogin} className="space-y-6">
            <div>
              <label htmlFor="admin-password" className="block text-sm font-bold uppercase tracking-[0.3em] text-gray-600 mb-3">
                Contraseña
              </label>
              <input
                id="admin-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoFocus
                placeholder="••••••••••••"
                className="w-full bg-transparent border border-gray-200 px-4 py-3 text-sm text-gray-800 focus:border-gray-900 outline-none transition-colors rounded"
              />
            </div>

            {error && (
              <p className="text-red-500 text-xs text-center font-medium">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading || !password}
              className="w-full bg-brand-red text-white py-4 font-bold uppercase tracking-widest text-xs hover:bg-black transition-all duration-300 disabled:opacity-50"
            >
              {loading ? 'Verificando...' : 'Entrar'}
            </button>
          </form>

          <p className="text-center text-sm text-gray-300 mt-8 uppercase tracking-widest">
            Solo para el equipo editorial
          </p>
        </div>

        <p className="text-center text-xs text-gray-300 mt-6">
          © <span suppressHydrationWarning>{new Date().getFullYear()}</span> RecetaDolce
        </p>
      </div>
    </div>
  );
}
