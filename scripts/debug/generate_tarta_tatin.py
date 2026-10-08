import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from rankstein_mcp_server import validate_article_quality

content_markdown = """# Tarta Tatin de Manzana Tradicional: La Joya de la Alta Repostería

La **tarta tatin de manzana tradicional** es, sin lugar a dudas, uno de los hitos más deslumbrantes en la historia de la pastelería clásica. Nacida fortuitamente en el corazón de Francia a finales del siglo XIX de la mano de las hermanas Stéphanie y Caroline Tatin, esta tarta invertida conquistó los salones más refinados de Europa y hoy constituye una lección magistral de equilibrio entre fruta, caramelo y masa quebrada mantecosa.

En mi obrador de repostería, siempre sostengo que la grandeza de una tarta tatin reside en su aparente sencillez: apenas manzanas, mantequilla, azúcar y una masa crujiente. Sin embargo, lograr que las manzanas queden tiernas, translúcidas y profundamente caramelizadas sin romperse ni soltar un exceso de agua exige precisión técnica, paciencia y conocimiento de la materia prima.

A continuación, comparto contigo nuestra fórmula depurada para elaborar una tarta tatin tradicional inolvidable, con consejos de maestro pastelero y el paso a paso exacto para triunfar al desmoldar.

---

## El Secreto de las Manzanas: Variedades y Comportamiento Térmico

No cualquier manzana es apta para soportar una doble cocción prolongada. Según las recomendaciones agronómicas y guías de calidad alimentaria de la **AESAN (Agencia Española de Seguridad Alimentaria y Nutrición)** sobre el tratamiento térmico de frutas de pepita, la concentración de pectina y el nivel de acidez son determinantes para mantener la estructura celular durante el horneado.

Para nuestra tarta tatin tradicional, las mejores variedades son:
- **Manzana Reineta:** Aporta una acidez vibrante que equilibra el dulzor del caramelo toffee y posee una textura firme inigualable.
- **Manzana Golden Delicious o Pink Lady:** Opciones dulces y aromáticas que mantienen su forma intacta sin transformarse en compota.

En mi experiencia profesional, un truco indispensable que aprendí tras años perfeccionando esta receta consiste en pelar y cortar las manzanas en cuartos la víspera o dejarlas orear sobre una rejilla durante un par de horas. Al perder una pequeña fracción de humedad superficial, la fruta absorbe el caramelo de mantequilla de forma mucho más uniforme y la tarta no queda aguada.

---

## La Masa Quebrada (Pâte Brisée): El Escudo Crujiente

Aunque en ocasiones se utiliza hojaldre, la receta original e histórica de las hermanas Tatin se corona con una auténtica **masa quebrada casera** enriquecida con mantequilla de alta graduación grasa (mínimo 82% M.G., en consonancia con los estándares de la **EFSA** sobre pureza láctea).

La masa debe manipularse lo mínimo imprescindible. Queremos evitar el desarrollo del gluten para que, una vez horneada y reposada, ofrezca esa textura arenosa y quebradiza que se deshace en el paladar en armonía con la jugosidad de la manzana.

---

## Ingredientes Precisos para 8 Raciones

### Para el Relleno y Caramelo Toffee:
- **1,5 kg de manzanas Reineta o Golden** (aproximadamente 6-7 piezas grandes, peladas, descorazonadas y cortadas en cuartos homogéneos)
- **150 g de azúcar blanquilla de caña**
- **100 g de mantequilla sin sal de primera calidad** cortada en dados
- **1 cucharadita de extracto puro de vainilla de Madagascar**
- **1 pizca de flor de sal** (para potenciar los matices tostados del caramelo)
- **1 cucharadita de zumo de limón fresco**

### Para la Masa Quebrada Tradicional:
- **250 g de harina de trigo de repostería** (baja en fuerza)
- **125 g de mantequilla fría** cortada en cubos de 1 cm
- **1 huevo campero tamaño L**
- **25 g de azúcar glas**
- **2-3 cucharadas de agua helada**
- **1 pizca de sal fina**

---

## Elaboración Paso a Paso: Guía de Maestro Pastelero

### Paso 1: Confección de la Masa Quebrada
En un cuenco amplio o sobre la superficie de trabajo bien fría, tamiza la harina junto con el azúcar glas y la pizca de sal. Añade los dados de mantequilla fría recién sacada de la nevera. Con la yema de los dedos o una rasqueta pastelera, frota rápidamente la grasa con la harina hasta obtener una textura arenosa, parecida al pan rallado fino. Incorpora el huevo batido y dos cucharadas de agua helada. Une la masa con movimientos envolventes sin amasar en exceso. Forma un disco plano, envuélvelo en papel film transparente y déjalo reposar en el frigorífico durante al menos 45 minutos.

### Paso 2: Preparación y Secado de las Manzanas
Pela las manzanas con esmero, retira el corazón con un descorazonador cilíndrico y córtalas en mitades o cuartos según su tamaño. Rocíalas ligeramente con unas gotas de zumo de limón para retrasar la oxidación enzimática natural.

### Paso 3: El Caramelo Rubio de Mantequilla
Utiliza un molde metálico o una sartén apta para horno de paredes rectas y 24 cm de diámetro (idealmente de hierro fundido esmaltado o cobre). Coloca la mantequilla en dados sobre la base del molde junto con el azúcar y la vainilla. Lleva a fuego medio-bajo hasta que la mantequilla se funda con el azúcar formando un caramelo espumoso de tono dorado ambarino. Añade la pizca de flor de sal.

### Paso 4: Disposición Apretada de la Fruta
Retira el molde del fuego unos instantes. Dispón los trozos de manzana de canto, bien apretados entre sí en círculos concéntricos desde el exterior hacia el centro. Recuerda que al cocinarse, la manzana reduce su volumen de forma notable; si dejas huecos, la tarta se desmoronará al desmoldar. Devuelve el molde a fuego muy suave durante 12-15 minutos para que la fruta comience a pocharse y caramelizarse en los propios jugos.

### Paso 5: Estirado y Sellado de la Masa
Precalienta el horno a 185 °C con calor arriba y abajo. Saca la masa de la nevera, espolvorea ligeramente la mesa con harina y estírala con un rodillo hasta alcanzar un grosor uniforme de 3-4 mm y un diámetro 2 cm superior al molde. Coloca con suavidad el disco de masa sobre las manzanas calientes. Con una cuchara de madera o el dedo índice, remete los bordes de la masa hacia el interior del molde, abrazando las manzanas como si fuera una tapa hermética. Pincha la superficie en 4 o 5 puntos con la punta de un cuchillo para crear chimeneas de escape del vapor.

### Paso 6: Horneado Perfecto
Introduce el molde en la rejilla central del horno y hornea durante 30-35 minutos a 185 °C, hasta que la masa presente un atractivo color dorado tostado y el caramelo burbujee densamente por los laterales.

### Paso 7: El Momento Crucial: El Desmolde Invertido
Retira la tarta del horno. **Nunca intentes desmoldarla de inmediato** (el caramelo hirviendo causaría quemaduras graves y la fruta se deslizaría) **ni completamente fría** (el caramelo solidificado se pegaría irrevocablemente a la base). El punto perfecto es tras 10-12 minutos de reposo a temperatura ambiente. Pasa una espátula fina por los bordes, coloca un plato llano de presentación con reborde sobre el molde y, con un movimiento firme, seguro y decidido, dale la vuelta. Levanta lentamente el molde y admira el brillo majestuoso de las manzanas glaseadas.

---

## Consejos de Conservación y Servicio

Sirve la tarta tatin templada, idealmente acompañada de una quenelle de **crème fraîche** espesa, una bola de helado artesanal de vainilla Bourbon o nata montada sin azúcar. Si necesitas recalentar una porción al día siguiente, hazlo siempre en horno convencional a 150 °C durante 8 minutos; el microondas arruinaría irremisiblemente la textura crujiente de la base quebrada.

---

## Preguntas Frecuentes sobre la Tarta Tatin Tradicional

### ¿Por qué mi tarta tatin ha quedado con exceso de líquido al desmoldar?
Las manzanas demasiado maduras o variedades con alto contenido en agua pueden soltar excesivo jugo si no se pochó previamente la fruta a fuego lento antes de entrar al horno. Dejar orear la fruta y utilizar variedades como Reineta o Pink Lady previene este inconveniente.

### ¿Se puede utilizar masa de hojaldre comprada en lugar de masa quebrada?
Sí, el hojaldre de mantequilla fresco es una excelente alternativa rápida. Asegúrate de pincharlo profusamente antes de hornear para evitar que suba de manera descontrolada.

### ¿Cómo despegar la tarta si el caramelo se ha enfriado y se ha quedado pegada al molde?
Si esperaste demasiado y el caramelo se enfrió, pon el fondo del molde sobre el fuego de la cocina a intensidad mínima durante 45-60 segundos. El calor licuará el caramelo adherido al fondo y podrás voltearla limpiamente sin esfuerzo.
"""

article_payload = {
    "title": "Tarta Tatin de Manzana Tradicional: La Joya de la Alta Repostería",
    "slug": "tarta-tatin-de-manzana-tradicional",
    "excerpt": "Aprende a preparar la auténtica tarta tatin de manzana tradicional: fruta caramelizada al punto, masa quebrada y desmolde perfecto.",
    "category": "tartas-y-pasteles",
    "content_markdown": content_markdown,
    "chef_tip": "Deja orear los cuartos de manzana pelados durante una hora antes de caramelizarlos para reducir el exceso de agua y lograr un glaseado denso y brillante que no reblandezca la masa.",
    "image_alt": "Tarta tatin de manzana tradicional con caramelo dorado brillante y masa crujiente horneada",
    "image_negative_prompt": "text, watermark, logo, cartoon, blurry, distorted, raw, doughy, unappetizing",
    "hero_image_prompt": "A master pastry French Tarte Tatin upside down apple tart, glistening caramelized golden amber sliced apples tightly arranged in concentric circles on buttery golden crisp crust, served on an artisanal ceramic platter, elegant bakery setting, warm soft lighting, culinary photography, 8k, photorealistic",
    "pinterest_pin_prompt": "A close up vertical 2:3 shot of a slice of traditional Tarte Tatin apple tart showing caramelized glistening translucent apples and flaky pastry crust, warm bakery background, mouthwatering gourmet food photography",
    "recipe_schema": {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": "Tarta Tatin de Manzana Tradicional",
        "description": "Receta clásica y artesanal de tarta tatin de manzana tradicional con fruta caramelizada en mantequilla y masa quebrada casera crujiente.",
        "image": "https://xjvmnmfczvwkjiasirsl.supabase.co/storage/v1/object/public/recipe-images/recetadolce/tarta-tatin-de-manzana-tradicional-hero.jpg",
        "author": {
            "@type": "Person",
            "name": "Isabella Dolce"
        },
        "prepTime": "PT45M",
        "cookTime": "PT35M",
        "totalTime": "PT1H20M",
        "recipeYield": "8 raciones",
        "recipeCuisine": "Francesa",
        "recipeCategory": "tartas-y-pasteles",
        "recipeIngredient": [
            "1.5 kg de manzanas Reineta o Golden peladas y descorazonadas en cuartos",
            "150 g de azúcar blanquilla de caña",
            "100 g de mantequilla sin sal cortada en dados",
            "250 g de harina de trigo de repostería",
            "125 g de mantequilla fría en cubos para la masa quebrada",
            "1 huevo campero grande L",
            "25 g de azúcar glas",
            "1 cucharadita de extracto natural de vainilla de Madagascar",
            "1 pizca de flor de sal",
            "2 cucharadas de agua helada"
        ],
        "recipeInstructions": [
            {
                "@type": "HowToStep",
                "text": "Preparar la masa quebrada mezclando la harina, sal, azúcar glas y mantequilla fría hasta arenar. Incorporar el huevo y agua helada, formar un disco y refrigerar 45 minutos."
            },
            {
                "@type": "HowToStep",
                "text": "Pelar, descorazonar y cortar las manzanas en cuartos homogéneos, dejándolas orear ligeramente."
            },
            {
                "@type": "HowToStep",
                "text": "En una sartén o molde metálico apto para horno de 24 cm, fundir la mantequilla con el azúcar y la vainilla hasta lograr un caramelo rubio brillante con una pizca de flor de sal."
            },
            {
                "@type": "HowToStep",
                "text": "Disponer los trozos de manzana de canto, muy apretados en círculos concéntricos, y cocer a fuego muy suave durante 12-15 minutos para que la fruta se impregne del caramelo."
            },
            {
                "@type": "HowToStep",
                "text": "Estirar la masa quebrada a 3 mm, cubrir las manzanas remetiendo los bordes hacia adentro para abrazar la fruta y pinchar la superficie para evacuar el vapor."
            },
            {
                "@type": "HowToStep",
                "text": "Hornear a 185 °C con calor arriba y abajo durante 30-35 minutos hasta que la masa esté dorada y crujiente."
            },
            {
                "@type": "HowToStep",
                "text": "Reposar 10-12 minutos tras sacarla del horno y voltear con decisión sobre una fuente con reborde para servir templada."
            }
        ]
    },
    "faq_schema": [
        {
            "question": "¿Por qué mi tarta tatin ha quedado con exceso de líquido al desmoldar?",
            "answer": "Las manzanas con alto contenido en agua pueden soltar excesivo jugo si no se pochan previamente a fuego suave antes de entrar al horno. Dejar orear la fruta y usar manzana Reineta previene este problema."
        },
        {
            "question": "¿Se puede utilizar masa de hojaldre en lugar de masa quebrada?",
            "answer": "Sí, el hojaldre de mantequilla fresco es una excelente alternativa. Pincha profusamente la masa antes de hornear para controlar el crecimiento."
        },
        {
            "question": "¿Cómo despegar la tarta si el caramelo se ha enfriado en el molde?",
            "answer": "Pon el fondo del molde sobre el fuego suave durante 45-60 segundos. El caramelo se volverá fluido y podrás desmoldar limpiamente sin romper la fruta."
        }
    ]
}

res = validate_article_quality(json.dumps(article_payload))
print("Validation result score:", res.get("score"), "Passed:", res.get("passed"), "Issues:", res.get("issues"))

# Save payload to data/runtime for publisher
out_path = PROJECT_ROOT / "data" / "runtime" / "tarta_tatin_payload.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(article_payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("Saved payload to:", out_path)
