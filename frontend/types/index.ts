export interface FAQItem {
  question: string;
  answer: string;
}

export interface FAQPage {
  "@type": "FAQPage";
  mainEntity: {
    "@type": "Question";
    name: string;
    acceptedAnswer: {
      "@type": "Answer";
      text: string;
    };
  }[];
}

export interface Review {
  id: string;
  created_at: string;
  post_id: string;
  author_name: string;
  author_avatar?: string;
  rating: number;
  content: string;
  status: 'pending' | 'approved' | 'rejected';
}

export type SpanishCategory =
  | 'Postres'
  | 'Tartas'
  | 'Galletas'
  | 'Helados & Cremas'
  | 'Bebidas'
  | 'Saludable'
  | 'Chocolate'
  | 'Tapas & Pinchos'
  | 'Arroces & Paella'
  | 'Sopas & Guisos'
  | 'Mariscos'
  | 'Carnes';

export const SPANISH_CATEGORIES: SpanishCategory[] = [
  'Postres',
  'Tartas',
  'Galletas',
  'Helados & Cremas',
  'Bebidas',
  'Saludable',
  'Chocolate',
  'Tapas & Pinchos',
  'Arroces & Paella',
  'Sopas & Guisos',
  'Mariscos',
  'Carnes',
];

export interface Post {
  id: string;
  created_at: string;
  published_at: string;
  title: string;
  slug: string;
  content: string;
  excerpt: string;
  hero_image: string;
  featured_image?: string | null;
  category?: string;
  category_id: string;
  is_published: boolean;
  status?: 'draft' | 'published';
  meta_title?: string | null;
  meta_description?: string | null;
  seo_title: string;
  seo_description: string;
  keywords: string[];
  geo_location: {
    name: string;
    lat: number;
    lng: number;
  } | null;
  recipe_schema: any | null;
  faq: FAQPage | FAQItem[] | null;
  step_images?: { step: number; url: string }[];
  rating_value: number;
  rating_count: number;
  updated_at: string;
  difficulty?: 'Fácil' | 'Media' | 'Difícil';
  estimated_cost?: 'Económico' | 'Medio' | 'Premium';
  prep_time?: number;
  cook_time?: number;
  cooking_time?: string;
  servings?: string;
  ingredients?: string[];
  instructions?: any[];
  image_alt?: string;
  chef_tip?: string;
  reviews?: Review[];
  pinterest_pin_id?: string;
  author?: string;
}
export interface Settings {
  id: string;
  created_at?: string;
  updated_at?: string;
  site_name: string;
  site_description: string;
  site_logo?: string;
  contact_email: string;
  navigation_menu?: { label: string; href: string }[];
  categories?: string[];
  google_analytics_id?: string;
  custom_head_code?: string;
  custom_footer_code?: string;
  facebook_url?: string;
  instagram_url?: string;
  pinterest_url?: string;
  twitter_url?: string;
  youtube_url?: string;
  tiktok_url?: string;
  seo_keywords?: string[];
  ads_enabled?: boolean;
  adsense_client_id?: string;
  ads_top_slot?: string;
  ads_middle_slot?: string;
  ads_bottom_slot?: string;
  ads_sidebar_slot?: string;
}
