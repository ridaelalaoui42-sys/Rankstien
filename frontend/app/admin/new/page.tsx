import PostForm from '@/components/PostForm';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

export const dynamic = 'force-dynamic';

export default async function NewPostPage() {
  const cookieStore = await cookies();
  const session = cookieStore.get('rd_admin_session');

  if (!session || session.value !== 'authenticated') {
    redirect('/admin/login');
  }

  return (
    <div className="min-h-screen bg-gray-50 py-12">
      <div className="container mx-auto px-6 max-w-4xl">
        <div className="mb-10">
          <h1 className="text-4xl font-serif text-gray-900 mb-1">Nueva Receta</h1>
          <p className="text-gray-600 font-bold uppercase tracking-widest text-sm">
            RecetaDolce · Crear contenido
          </p>
        </div>
        <div className="bg-white border border-gray-100 p-10">
          <PostForm />
        </div>
      </div>
    </div>
  );
}
