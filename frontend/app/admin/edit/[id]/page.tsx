import { createClient } from '@supabase/supabase-js';
import { notFound, redirect } from 'next/navigation';
import { cookies } from 'next/headers';
import PostForm from '@/components/PostForm';

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EditPostPage({ params }: Props) {
  const cookieStore = await cookies();
  const session = cookieStore.get('rd_admin_session');

  if (!session || session.value !== 'authenticated') {
    redirect('/admin/login');
  }

  const { id } = await params;

  // Use service role on server to ensure we can fetch the post for editing
  const supabaseAdmin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL || '',
    process.env.SUPABASE_SERVICE_ROLE_KEY || ''
  );

  const { data: post } = await supabaseAdmin
    .from('posts')
    .select('*')
    .eq('id', id)
    .single();

  if (!post) notFound();

  return (
    <div className="min-h-screen bg-gray-50 py-12">
      <div className="container mx-auto px-6 max-w-4xl">
        <div className="mb-10">
          <h1 className="text-4xl font-serif text-gray-900 mb-1">Editar Receta</h1>
          <p className="text-gray-600 font-bold uppercase tracking-widest text-sm">
            {post.title}
          </p>
        </div>
        <div className="bg-white border border-gray-100 p-10">
          <PostForm post={post} />
        </div>
      </div>
    </div>
  );
}
