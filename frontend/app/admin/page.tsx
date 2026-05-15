import Link from 'next/link';
import { createClient } from '@supabase/supabase-js';
import { Post } from '@/types';
import DeleteButton from '@/components/DeleteButton';
import LogoutButton from '@/components/LogoutButton';

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

export const metadata = {
  title: 'Panel Admin | RecetaDolce',
  robots: { index: false, follow: false },
};

async function getAdminPosts() {
  try {
    // Admin dashboard MUST use service role to bypass RLS and see all content
    const supabaseAdmin = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL || '',
      process.env.SUPABASE_SERVICE_ROLE_KEY || ''
    );

    const { data: posts, error } = await supabaseAdmin
      .from('posts')
      .select('*')
      .order('created_at', { ascending: false });

    if (error) {
      console.error('Supabase error:', error);
      return [];
    }
    return (posts as Post[]) || [];
  } catch (err) {
    console.error('Fetch error:', err);
    return [];
  }
}

const CATEGORY_COLORS: Record<string, string> = {
  'postres': 'bg-pink-50 text-pink-700',
  'tapas': 'bg-amber-50 text-amber-700',
  'mariscos': 'bg-blue-50 text-blue-700',
  'carnes': 'bg-red-50 text-red-700',
  'arroces': 'bg-yellow-50 text-yellow-700',
  'helados': 'bg-purple-50 text-purple-700',
};

function catColor(cat: string | null | undefined) {
  if (!cat) return 'bg-gray-100 text-gray-600';
  const key = Object.keys(CATEGORY_COLORS).find((k) => cat.toLowerCase().includes(k));
  return key ? CATEGORY_COLORS[key] : 'bg-gray-100 text-gray-600';
}

export default async function AdminDashboard() {
  const cookieStore = await cookies();
  const session = cookieStore.get('rd_admin_session');

  if (!session || session.value !== 'authenticated') {
    redirect('/admin/login');
  }

  const posts = await getAdminPosts();

  const stats = {
    total: posts.length,
    published: posts.filter((p) => p.status === 'published').length,
    drafts: posts.filter((p) => p.status === 'draft').length,
    categories: new Set(posts.map((p) => p.category)).size,
  };

  return (
    <div className="min-h-screen bg-gray-50 py-6 sm:py-12">
      <div className="container mx-auto px-4 sm:px-6">

        {/* Header */}
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 sm:mb-12 space-y-4 md:space-y-0 gap-4">
          <div className="w-full md:w-auto">
            <h1 className="text-2xl sm:text-4xl font-serif text-gray-900 mb-1">Panel Editorial</h1>
            <div className="flex flex-wrap items-center gap-2 sm:gap-4">
              <p className="text-gray-600 font-bold uppercase tracking-widest text-xs sm:text-sm">       
                RecetaDolce · Gestión de Contenidos
              </p>
              <span className="text-gray-200">|</span>
              <LogoutButton />
            </div>
          </div>
          <div className="flex w-full md:w-auto gap-2 sm:gap-4">
            <Link
              href="/"
              className="flex-1 md:flex-none text-center border border-gray-200 text-gray-600 px-4 sm:px-6 py-3 font-bold uppercase tracking-widest text-sm sm:text-xs hover:bg-white transition-all"
            >
              Ver Sitio
            </Link>
            <Link
              href="/admin/new"
              className="flex-1 md:flex-none text-center bg-brand-red text-white px-4 sm:px-8 py-3 font-bold uppercase tracking-widest text-sm sm:text-xs hover:bg-red-800 transition-all flex items-center justify-center space-x-2"
            >
              <span>+</span><span>Nueva Receta</span>
            </Link>
          </div>
        </header>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4 mb-8 sm:mb-12">
          {[
            { label: 'Total Recetas', value: stats.total, color: 'text-gray-900' },
            { label: 'Publicadas', value: stats.published, color: 'text-green-600' },
            { label: 'Borradores', value: stats.drafts, color: 'text-gray-600' },
            { label: 'Categorías', value: stats.categories, color: 'text-brand-red' },
          ].map((stat) => (
            <div key={stat.label} className="bg-white p-4 sm:p-6 border border-gray-100">
              <p className="text-xs sm:text-sm font-bold text-gray-600 uppercase tracking-[0.2em] sm:tracking-[0.25em] mb-2 sm:mb-3">{stat.label}</p>
              <p className={`text-3xl sm:text-4xl font-serif ${stat.color}`}>{stat.value}</p>
            </div>
          ))}
        </div>

        {/* Quick links */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-12">
          {[
            { label: 'Configuración Global', href: '/admin/settings', desc: 'Personaliza tu sitio y analytics' },
            { label: 'Auditoría SEO', href: '/admin/seo-audit', desc: 'Encuentra y arregla problemas SEO' },
            { label: 'Newsletter', href: '/admin/newsletter', desc: 'Gestiona tu lista de suscriptores' },
            { label: 'Nueva Receta', href: '/admin/new', desc: 'Crea contenido optimizado con IA' },
          ].map((link) => (
            <Link
              key={link.label}
              href={link.href}
              className="bg-white border border-gray-100 p-6 hover:border-brand-red transition-colors group shadow-sm"    
            >
              <p className="font-bold text-sm text-gray-800 group-hover:text-brand-red transition-colors mb-1">{link.label}</p>
              <p className="text-xs text-gray-600">{link.desc}</p>
            </Link>
          ))}
        </div>

        {/* Table */}
        <div className="bg-white border border-gray-100 overflow-hidden">
          <div className="px-8 py-5 border-b border-gray-100 flex justify-between items-center">
            <h2 className="text-sm font-bold uppercase tracking-[0.2em] text-gray-600">Todas las Recetas</h2>   
            <span className="text-sm text-gray-600">{posts.length} recetas</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[700px]">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="px-8 py-4 text-sm font-black uppercase tracking-[0.25em] text-gray-600">Receta</th>
                  <th className="px-8 py-4 text-sm font-black uppercase tracking-[0.25em] text-gray-600">Categoría</th>
                  <th className="px-8 py-4 text-sm font-black uppercase tracking-[0.25em] text-gray-600">Estado</th>
                  <th className="px-8 py-4 text-sm font-black uppercase tracking-[0.25em] text-gray-600">Fecha</th>
                  <th className="px-8 py-4 text-sm font-black uppercase tracking-[0.25em] text-gray-600 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {posts.map((post) => (
                  <tr key={post.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-8 py-5">
                      <div className="font-serif text-gray-800 mb-1 truncate max-w-[260px]">{post.title}</div>  
                      <div className="text-sm text-gray-600 font-mono">/{post.slug}</div>
                    </td>
                    <td className="px-8 py-5">
                      <span className={`text-sm font-bold px-3 py-1 rounded uppercase tracking-wider ${catColor(post.category)}`}>
                        {post.category || 'Sin categoría'}
                      </span>
                    </td>
                    <td className="px-8 py-5">
                      <div className="flex items-center space-x-2">
                        <span className={`w-2 h-2 rounded-full ${post.status === 'published' ? 'bg-green-500' : 'bg-gray-300'}`} />
                        <span className="text-xs text-gray-600">
                          {post.status === 'published' ? 'Publicada' : 'Borrador'}
                        </span>
                      </div>
                    </td>
                    <td className="px-8 py-5 text-xs text-gray-600">
                      <span suppressHydrationWarning>{new Date(post.created_at).toLocaleDateString('es-ES')}</span>
                    </td>
                    <td className="px-8 py-5 text-right space-x-4">
                      <Link href={`/${post.slug}`} target="_blank" className="text-gray-600 text-xs hover:text-gray-700 transition-colors">
                        Ver
                      </Link>
                      <Link href={`/admin/edit/${post.id}`} className="text-brand-red font-bold text-xs hover:underline">
                        Editar
                      </Link>
                      <DeleteButton postId={post.id} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {posts.length === 0 && (
            <div className="py-20 text-center">
              <p className="text-gray-600 italic font-serif">No hay recetas aún. ¡Empieza creando una!</p>    
            </div>
          )}
        </div>

        {/* Admin Access Info */}
        <div className="mt-8 bg-amber-50 border border-amber-100 px-6 py-4 text-xs text-amber-700">
          <strong>Estado de sesión:</strong> El botón Admin aparece automáticamente en la barra de navegación tras iniciar sesión. Si no lo ves, intenta recargar la página.
        </div>
      </div>
    </div>
  );
}
