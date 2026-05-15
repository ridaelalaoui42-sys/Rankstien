const { createClient } = require('@supabase/supabase-js');
require('dotenv').config({ path: '.env.local' });

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!supabaseKey) {
    console.error('SUPABASE_SERVICE_ROLE_KEY is missing from .env.local');
    process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

const categories = [
  { name: 'Aperitivos', slug: 'aperitivos', description: 'Tapas, entrantes y aperitivos deliciosos.' },
  { name: 'Arroces', slug: 'arroces', description: 'Paellas, risottos y los mejores platos de arroz.' },
  { name: 'Carnes', slug: 'carnes', description: 'Recetas de pollo, cerdo, ternera y más.' },
  { name: 'Pescados', slug: 'pescados', description: 'Lo mejor del mar: pescados y mariscos frescos.' },
  { name: 'Ensaladas', slug: 'ensaladas', description: 'Ensaladas frescas y saludables para todo el año.' },
  { name: 'Postres', slug: 'postres', description: 'Dulces, tartas y postres irresistibles.' }
];

const navigation = [
  { label: 'Inicio', path: '/', order_index: 0 },
  { label: 'Aperitivos', path: '/categoria/aperitivos', order_index: 1 },
  { label: 'Arroces', path: '/categoria/arroces', order_index: 2 },
  { label: 'Carnes', path: '/categoria/carnes', order_index: 3 },
  { label: 'Pescados', path: '/categoria/pescados', order_index: 4 },
  { label: 'Ensaladas', path: '/categoria/ensaladas', order_index: 5 },
  { label: 'Postres', path: '/categoria/postres', order_index: 6 },
  { label: 'Sobre Nosotros', path: '/sobre-nosotros', order_index: 7 }
];

async function seedDatabase() {
  console.log('Seeding categories...');
  for (const cat of categories) {
    const { error } = await supabase
      .from('categories')
      .upsert(cat, { onConflict: 'slug' });
    if (error) console.error(`Error seeding category ${cat.name}:`, error.message);
    else console.log(`Category ${cat.name} seeded.`);
  }

  console.log('Seeding navigation...');
  // Clear existing navigation to avoid duplicates if order_index is not unique
  await supabase.from('navigation').delete().neq('id', '00000000-0000-0000-0000-000000000000'); 
  
  for (const nav of navigation) {
    const { error } = await supabase
      .from('navigation')
      .insert(nav);
    if (error) console.error(`Error seeding navigation ${nav.label}:`, error.message);
    else console.log(`Navigation ${nav.label} seeded.`);
  }

  console.log('Database seeding completed.');
}

seedDatabase();
