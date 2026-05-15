
import { supabase } from '@/lib/supabase';
import { Post } from '@/types';
import Link from 'next/link';
import Image from 'next/image';

interface RelatedPostsProps {
  currentPostId: string;
  category: string;
}

export default async function RelatedPosts({ currentPostId, category }: RelatedPostsProps) {
  const { data: posts } = await supabase
    .from('posts')
    .select('*')
    .eq('category', category)
    .eq('status', 'published')
    .neq('id', currentPostId)
    .limit(3);

  if (!posts || posts.length === 0) return null;

  return (
    <section>
      <div className="flex items-center space-x-6 mb-12">
        <span className="text-editorial text-brand-fresa uppercase tracking-[0.4em] text-sm font-bold">También te puede gustar</span>
        <div className="flex-1 h-px bg-brand-fresa/10" />
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
        {(posts as Post[]).map((post) => (
          <Link key={post.id} href={`/${post.slug}`} className="group block">
            <div className="relative aspect-[16/10] mb-6 overflow-hidden rounded-2xl bg-cream-dark card-shadow group-hover:card-shadow-hover transition-all duration-500">
              {post.hero_image ? (
                <Image
                  src={post.hero_image}
                  alt={post.title}
                  fill
                  sizes="(max-width: 768px) 100vw, 33vw"
                  className="object-cover group-hover:scale-110 transition-transform duration-700"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-brand-fresa/10 font-serif text-4xl">RD</div>
              )}
            </div>
            <h4 className="text-xl font-serif text-ink group-hover:text-brand-fresa transition-colors leading-snug">
              {post.title}
            </h4>
            <p className="text-xs text-gray-600 mt-3 font-bold uppercase tracking-widest italic opacity-60">
              {post.category}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}
