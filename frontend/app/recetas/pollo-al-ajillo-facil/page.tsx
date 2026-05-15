import { Metadata } from 'next';
import styles from './recipe.module.css';
import RecipeHero from '@/components/recipe/RecipeHero';
import IngredientsList from '@/components/recipe/IngredientsList';
import StepByStep from '@/components/recipe/StepByStep';
import FAQSection from '@/components/recipe/FAQSection';
import SocialShare from '@/components/recipe/SocialShare';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Pollo al Ajillo Fácil - Receta Española Cremosa | Paso a Paso',
  description: 'Aprende a hacer pollo al ajillo cremoso y delicioso en 30 minutos. Receta fácil, auténtica y familiar. Ingredientes simples, resultados espectaculares.',
  keywords: ['pollo al ajillo', 'receta española', 'cena fácil', 'pollo cremoso', 'pollo al ajillo fácil'],
  openGraph: {
    title: 'Pollo al Ajillo Fácil: La Receta Auténtica Española',
    description: 'La mejor receta de pollo al ajillo: cremosa, rápida y con todo el sabor de España.',
    images: ['/images/recipes/pollo-al-ajillo-facil.png'],
  }
};

const recipeData = {
  ingredients: [
    { name: 'Pechugas de pollo sin hueso', amount: '800g', notes: 'Cortadas en trozos medianos' },
    { name: 'Ajo fresco', amount: '10-12 dientes', notes: 'Picados finamente' },
    { name: 'Aceite de oliva virgen extra', amount: '100ml', notes: 'Calidad buena es importante' },
    { name: 'Vino blanco seco', amount: '150ml', notes: 'Vino de cocina estándar' },
    { name: 'Caldo de pollo', amount: '200ml', notes: 'Casero o de brick' },
    { name: 'Crema para cocinar', amount: '100ml', notes: 'Opcional, para cremosidad' },
    { name: 'Sal', amount: 'Al gusto', notes: 'Marina o de mesa' },
    { name: 'Pimienta negra', amount: 'Al gusto', notes: 'Recién molida' },
    { name: 'Perejil fresco', amount: '1 puñado', notes: 'Para decoración final' },
    { name: 'Limón', amount: '1', notes: 'Para acidez final' },
  ],
  steps: [
    {
      title: 'Preparar los Ingredientes',
      description: 'Corta el pollo en trozos medianos (unos 5-6cm). Pica el ajo finamente a mano. Mide el vino, el caldo, y la crema en recipientes separados.',
      tip: 'Si el pollo es muy grueso, puedes cubrirlo con papel film y aplastarlo ligeramente antes de dorarlo para una cocción uniforme.'
    },
    {
      title: 'Dorar el Pollo',
      description: 'Calienta el aceite de oliva a fuego medio-alto. Coloca el pollo y déjalo sin mover 3-4 minutos por lado hasta que esté bien dorado. Retíralo a un plato.',
      important: 'El pollo no necesita estar cocinado del todo aquí, solo buscamos un color dorado exterior.'
    },
    {
      title: 'Cocinar el Ajo',
      description: 'En la misma sartén con el aceite restante, baja el fuego a medio y añade el ajo picado. Remueve constantemente durante 2-3 minutos.',
      important: 'El ajo se quema muy rápido. Si se oscurece demasiado, baja el fuego. El ajo quemado amarga toda la salsa.'
    },
    {
      title: 'Desglazar con Vino y Caldo',
      description: 'Vierte el vino blanco y usa una espátula para raspar el fondo (el "pegote" dorado es puro sabor). Deja reducir 2-3 minutos y luego añade el caldo.',
    },
    {
      title: 'Cocinar el Pollo en la Salsa',
      description: 'Devuelve el pollo a la sartén. Baja el fuego a medio-bajo y cuece 8-10 minutos. Si quieres la versión cremosa, añade la crema ahora.',
      tip: 'Hazlo con muslos en lugar de pechugas si prefieres carne más jugosa; solo extiende el tiempo 3-5 minutos más.'
    },
    {
      title: 'Terminar y Servir',
      description: 'Prueba y ajusta sal/pimienta. Exprime un poco de limón fresco y decora con perejil picado.',
    }
  ],
  faqs: [
    { question: '¿Cuánto tiempo tarda hacer pollo al ajillo?', answer: 'Aproximadamente 30 minutos total: 10 minutos de preparación y 20 minutos de cocción.' },
    { question: '¿Se puede congelar pollo al ajillo?', answer: 'Sí, el pollo al ajillo congela muy bien hasta 3 meses en porciones individuales.' },
    { question: '¿Se puede hacer pollo al ajillo sin crema?', answer: 'Sí, la crema es opcional. Sin ella, la salsa es más ligera pero igual de deliciosa.' },
    { question: '¿Qué acompañamientos van bien?', answer: 'Pan tostado, arroz blanco, patatas paja, ensalada fresca o espinacas salteadas.' }
  ]
};

const recipeSchema = {
  "@context": "https://schema.org/",
  "@type": "Recipe",
  "name": "Pollo al Ajillo Fácil",
  "description": "Receta auténtica española de pollo al ajillo cremoso y delicioso, preparada en menos de 30 minutos con ingredientes simples.",
  "image": ["/images/recipes/pollo-al-ajillo-facil.png"],
  "author": { "@type": "Person", "name": "RecetaDolce Editorial" },
  "prepTime": "PT10M",
  "cookTime": "PT20M",
  "totalTime": "PT30M",
  "recipeYield": "4 porciones",
  "recipeCategory": "Plato Principal",
  "recipeCuisine": "Española",
  "recipeIngredient": recipeData.ingredients.map(i => `${i.amount} ${i.name}`),
  "recipeInstructions": recipeData.steps.map((s, i) => ({
    "@type": "HowToStep",
    "name": s.title,
    "text": s.description,
    "position": i + 1
  }))
};

export default function PolloAlAjilloPage() {
  return (
    <main className={styles.container}>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(recipeSchema) }}
      />
      
      <RecipeHero 
        title="Pollo al Ajillo Fácil: La Receta Auténtica Española"
        category="Plato Principal"
        slug="recetas/pollo-al-ajillo-facil"
        prepTime="10 MIN"
        cookTime="20 MIN"
        difficulty="FÁCIL"
        readTime={6}
        author="Isabella Dolce"
      />

      <div className={styles.contentGrid}>
        <article className={styles.mainContent}>
          <p className="lead text-2xl font-serif italic mb-8 color-brand-fresa-deep">
            El pollo al ajillo es uno de esos platos que define la cocina española: simple, elegante, y absolutamente irresistible.
          </p>
          
          <p>
            Con apenas un puñado de ingredientes—pollo, ajo, aceite de oliva, y vino blanco—creas una salsa cremosa y aromática que transforma pechugas ordinarias en algo verdaderamente especial. Esta receta es perfecta para familias ocupadas. Se prepara en menos de 30 minutos, requiere solo una sartén, y funciona igual de bien para una comida casual entre semana como para impresionar a invitados.
          </p>

          <SocialShare 
            title="Pollo al Ajillo Fácil: La Receta Auténtica Española"
            url="https://RecetaDolce.com/recetas/pollo-al-ajillo-facil"
          />

          <StepByStep steps={recipeData.steps} />

          <section className="my-16">
            <h2 className="font-serif text-3xl mb-6">Variaciones: Personaliza tu Plato</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-6 bg-cream-soft rounded-xl">
                <h4 className="font-bold mb-2">Versión con Champiñones</h4>
                <p className="text-sm">Añade 250g de champiñones laminados junto con el ajo. Absorben los sabores y añaden textura.</p>
              </div>
              <div className="p-6 bg-cream-soft rounded-xl">
                <h4 className="font-bold mb-2">Versión Picante</h4>
                <p className="text-sm">Incorpora 1-2 guindillas secas con el ajo para un toque de calor español.</p>
              </div>
            </div>
          </section>

          <section className="my-16">
            <h2 className="font-serif text-3xl mb-6">Acompañamientos Perfectos</h2>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <li className="flex items-center gap-2">
                <span className="fresa-dot"></span>
                <Link href="/recetas/pan-de-ajo" className="hover-fresa-line">Pan Tostado con Ajo</Link>
              </li>
              <li className="flex items-center gap-2">
                <span className="fresa-dot"></span>
                <Link href="/recetas/arroz-blanco" className="hover-fresa-line">Arroz Blanco Suave</Link>
              </li>
              <li className="flex items-center gap-2">
                <span className="fresa-dot"></span>
                <Link href="/recetas/vinagreta-espanola" className="hover-fresa-line">Vinagreta Española</Link>
              </li>
              <li className="flex items-center gap-2">
                <span className="fresa-dot"></span>
                <Link href="/recetas/espinacas-salteadas" className="hover-fresa-line">Espinacas Salteadas</Link>
              </li>
              <li className="flex items-center gap-2">
                <span className="fresa-dot"></span>
                <Link href="/recetas/guarniciones" className="hover-fresa-line">Patatas Paja o Chips</Link>
              </li>
              <li className="flex items-center gap-2">
                <span className="fresa-dot"></span>
                <Link href="/recetas/pollo-al-chilindron" className="hover-fresa-line">Pollo al Chilindrón</Link>
              </li>
            </ul>
          </section>

          <section className="my-16 p-8 bg-brand-fresa/5 rounded-3xl border border-brand-fresa/10">
            <h2 className="font-serif text-3xl mb-6 text-brand-fresa-deep">Secretos de Chef para el Éxito</h2>
            <div className="space-y-6">
              <div>
                <h4 className="font-bold flex items-center gap-2">
                  <span className="w-2 h-2 bg-brand-fresa rounded-full"></span>
                  El Ajo es el Protagonista
                </h4>
                <p className="text-sm opacity-80">Usa siempre ajo fresco. Evita el ajo en polvo o de bote. Si el diente de ajo tiene un brote verde en el centro, retíralo para evitar amargor.</p>
              </div>
              <div>
                <h4 className="font-bold flex items-center gap-2">
                  <span className="w-2 h-2 bg-brand-fresa rounded-full"></span>
                  No Apures el Dorado
                </h4>
                <p className="text-sm opacity-80">La paciencia es clave. El ajo debe bailar en el aceite a fuego medio hasta que esté dorado y fragante, nunca marrón oscuro o negro.</p>
              </div>
              <div>
                <h4 className="font-bold flex items-center gap-2">
                  <span className="w-2 h-2 bg-brand-fresa rounded-full"></span>
                  Calidad del Pollo
                </h4>
                <p className="text-sm opacity-80">Si puedes, elige pollo de corral. Tiene menos agua y más sabor, lo que ayuda a que la salsa se emulsione mejor.</p>
              </div>
            </div>
          </section>

          <FAQSection faqs={recipeData.faqs} />
        </article>

        <aside className={styles.sidebar}>
          <IngredientsList ingredients={recipeData.ingredients} />
          
          <div className={`${styles.card} bg-brand-fresa text-white`}>
            <h3 className="font-serif text-2xl mb-4">¿Te ha gustado?</h3>
            <p className="mb-6 opacity-90 text-sm">Suscríbete para recibir recetas exclusivas y trucos de cocina española cada semana.</p>
            <button className="w-full py-3 bg-white text-brand-fresa font-bold rounded-full hover:scale-105 transition-transform">
              ¡Me apunto!
            </button>
          </div>
        </aside>
      </div>
    </main>
  );
}
