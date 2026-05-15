import Script from 'next/script';

interface SchemaMarkupProps {
  type?: 'Recipe' | 'Article' | 'FAQPage' | 'LocalBusiness' | 'BreadcrumbList' | 'Organization' | 'CollectionPage' | 'WebSite' | 'WebPage';
  data: any;
  id?: string;
}

export default function SchemaMarkup({ type, data, id }: SchemaMarkupProps) {
  const schema: any = {
    "@context": "https://schema.org",
    ...data
  };

  if (type && !data['@graph']) {
    schema["@type"] = type;
  }

  // Use a stable, deterministic ID to avoid hydration mismatches.
  // Math.random() caused server/client ID mismatch crashes.
  const scriptId = id || `schema-${type || 'graph'}`;

  return (
    <Script
      id={scriptId}
      type="application/ld+json"
      strategy="afterInteractive"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
    />
  );
}
