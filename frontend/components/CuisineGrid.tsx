import SafeImage from './SafeImage';
import Link from 'next/link';
import { SITE_IMAGES } from '@/lib/siteImages';

const cuisines = [
  { name: 'Pasteles', image: SITE_IMAGES.categories.pasteles, slug: 'pasteles' },
  { name: 'Galletas', image: SITE_IMAGES.categories.galletas, slug: 'galletas' },
  { name: 'Chocolates', image: SITE_IMAGES.categories.chocolates, slug: 'chocolates' },
  { name: 'Reposteria', image: SITE_IMAGES.categories.reposteria, slug: 'reposteria' },
  { name: 'Helados', image: SITE_IMAGES.categories.helados, slug: 'helados' },
  { name: 'Postres', image: SITE_IMAGES.categories.postres, slug: 'postres' },
];

export default function CuisineGrid() {
  return (
    <section className="py-12 bg-white rounded-[2rem] border border-cream-dark shadow-sm">
      <div className="text-center mb-10">
        <h2 className="text-2xl md:text-3xl font-serif text-ink mb-4">Nuestras Colecciones</h2>
        <div className="w-16 h-px bg-brand-fresa/50 mx-auto"></div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-6 px-6">
        {cuisines.map((cuisine) => (
          <Link key={cuisine.slug} href={`/categoria/${cuisine.slug}`} className="group flex flex-col items-center">
            <div className="relative w-20 h-20 md:w-28 md:h-28 rounded-full overflow-hidden border-4 border-cream-base group-hover:border-brand-fresa/20 transition-colors duration-500 shadow-sm group-hover:shadow-lg">
              <SafeImage
                src={cuisine.image}
                alt={cuisine.name}
                fill
                sizes="(max-width: 768px) 33vw, 16vw"
                className="object-cover group-hover:scale-110 transition-transform duration-700"
              />
            </div>
            <h3 className="mt-4 font-serif text-sm md:text-base text-ink group-hover:text-brand-fresa transition-colors">
              {cuisine.name}
            </h3>
          </Link>
        ))}
      </div>
    </section>
  );
}
