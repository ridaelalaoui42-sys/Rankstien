
import React from 'react';
import { Post } from '@/types';
import StandardRecipeCard from './StandardRecipeCard';
import RecipeGridToggle from './RecipeGridToggle';

interface RecipeGridProps {
  posts: Post[];
  initialCount?: number;
}

export default function RecipeGrid({ posts, initialCount = 6 }: RecipeGridProps) {
  if (posts.length === 0) return null;

  const initialPosts = posts.slice(0, initialCount);
  const remainingPosts = posts.slice(initialCount);

  return (
    <div className="space-y-16">
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-x-8 gap-y-12">
        {initialPosts.map((post) => (
          <StandardRecipeCard key={post.id} post={post} />
        ))}
        
        {posts.length > initialCount && (
          <RecipeGridToggle>
            {remainingPosts.map((post) => (
              <StandardRecipeCard key={post.id} post={post} />
            ))}
          </RecipeGridToggle>
        )}
      </div>
    </div>
  );
}
