
import Link from 'next/link';
import { FaChevronRight, FaHome } from 'react-icons/fa';

interface BreadcrumbsProps {
  items: {
    label: string;
    href: string;
    current?: boolean;
  }[];
}

export default function Breadcrumbs({ items }: BreadcrumbsProps) {
  return (
    <nav className="flex" aria-label="Breadcrumb">
      <ol className="flex items-center space-x-4">
        <li>
          <div>
            <Link href="/" className="text-gray-600 hover:text-brand-fresa transition-colors">
              <FaHome className="flex-shrink-0 h-4 w-4" aria-hidden="true" />
              <span className="sr-only">Inicio</span>
            </Link>
          </div>
        </li>
        {items.map((item, index) => (
          <li key={index}>
            <div className="flex items-center">
              <FaChevronRight className="flex-shrink-0 h-3 w-3 text-gray-300 mx-2" aria-hidden="true" />
              <Link
                href={item.href}
                className={`text-sm font-bold uppercase tracking-[0.2em] transition-colors ${
                  item.current 
                    ? 'text-brand-fresa pointer-events-none' 
                    : 'text-gray-600 hover:text-brand-fresa'
                }`}
                aria-current={item.current ? 'page' : undefined}
              >
                {item.label}
              </Link>
            </div>
          </li>
        ))}
      </ol>
    </nav>
  );
}
