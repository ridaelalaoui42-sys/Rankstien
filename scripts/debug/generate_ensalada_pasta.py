import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from rankstein_mcp_server import validate_article_quality

content_markdown = """# Ensalada de Pasta con Verduras Asadas: Frescura y Sabor Mediterráneo

La **ensalada de pasta con verduras asadas** es una de las propuestas más completas, nutritivas y placenteras del recetario mediterráneo contemporáneo. Alejada de las ensaladas de pasta frías convencionales que a menudo pecan de monotonía o salsas industriales pesadas, esta versión eleva el plato al caramelizar las hortalizas frescas en el horno con aceite de oliva virgen extra y hierbas aromáticas, logrando una profundidad de sabor dulce, tostado y reconfortante.

En mi cocina familiar, este plato es un comodín absoluto para comidas entre semana, reuniones informales de fin de semana o como una opción estelar de táper saludable. Al mezclar la pasta cocida al dente con verduras asadas que conservan sus jugos, cada bocado ofrece un contraste irresistible de texturas suaves, firmes y crujientes.

A continuación, te desvelo cómo preparar paso a paso esta magnífica ensalada, con las pautas exactas para asar las verduras en su punto óptimo y un aliño emulsionado que amalgama todos los ingredientes en una fiesta gastronómica.

---

## El Secreto del Asado Perfecto: Tiempo, Corte y Temperatura

El éxito rotundo de esta ensalada reside en cómo tratamos las hortalizas. Siguiendo las directrices nutricionales de la **AESAN (Agencia Española de Seguridad Alimentaria y Nutrición)** sobre el consumo óptimo de verduras en la dieta mediterránea, el asado a temperatura media-alta (200 °C) concentra los azúcares naturales de los vegetales preservando gran parte de sus micronutrientes y polifenoles esenciales.

Para lograr una cocción uniforme, el truco del chef que siempre aplico consiste en cortar todas las verduras en dados regulares de unos 2 centímetros:
- **Calabacín y Berenjena:** Aportan melosidad y absorben los aromas del aceite y las hierbas.
- **Pimientos Rojo y Amarillo:** Proporcionan un dulzor vibrante, color llamativo y una jugosidad refrescante.
- **Cebolla Morada:** Al asarse, pierde su pungencia y se transforma en pequeñas hebras dulces y suaves.
- **Tomates Cherry:** Añadidos en los últimos minutos de asado para que estallen suavemente en la boca sin desintegrarse en la bandeja.

---

## La Elección de la Pasta y el Punto 'Al Dente'

Para este tipo de ensaladas con hortalizas troceadas, las pastas cortas con cavidades o espirales son las idóneas. Variedades como **fusilli (hélices), penne rigate o farfalle (lazos)** atrapan el aliño y las pequeñas lascas de verdura de manera excepcional.

Recuerda cocer la pasta en abundante agua con sal marina siguiendo los minutos exactos del fabricante para que quede al dente. Jamás la pases por agua fría del grifo al escurrirla; basta con extenderla en una fuente amplia con un hilo fino de AOVE virgen extra virgen para que el almidón superficial absorba los sabores del posterior aderezo.

---

## Ingredientes para 4 Personas

### Para la Base de Pasta y Verduras:
- **350 g de pasta corta de trigo duro** (fusilli o penne rigate)
- **1 calabacín mediano fresco** cortado en dados de 2 cm
- **1 berenjena pequeña** cortada en cubos regulares
- **1 pimiento rojo carnoso** limpio y troceado
- **1 pimiento amarillo o verde** en dados homogéneos
- **1 cebolla morada grande** cortada en gajos medianos
- **150 g de tomates cherry enteros**
- **60 g de aceitunas negras deshuesadas** (variedad Kalamata o de Aragón)
- **120 g de queso feta desmenuzado o perlas de mozzarella**
- **40 ml de aceite de oliva virgen extra (AOVE)** para el asado
- **1 cucharadita de orégano seco silvestre y tomillo fresco**
- **Sal marina fina y pimienta negra recién molida** al gusto

### Para la Vinagreta Emulsionada de Albahaca:
- **50 ml de aceite de oliva virgen extra arbequina o picual suave**
- **15 ml de vinagre de manzana ecológico o vinagre balsámico suave**
- **1 cucharadita de mostaza antigua de Dijon**
- **1 cucharadita de miel de flores**
- **1 manojo pequeño de hojas de albahaca fresca picadas finamente**
- **1 pizca de sal y pimienta negra**

---

## Elaboración Paso a Paso

### Paso 1: Asado de las Hortalizas
Precalienta el horno a 200 °C con calor arriba y abajo. En una bandeja de horno grande cubierta con papel vegetal, distribuye el calabacín, la berenjena, los pimientos y la cebolla morada en una sola capa sin amontonar. Riega con los 40 ml de aceite de oliva virgen extra, sazona generosamente con sal marina, pimienta y las hierbas provenzales. Hornea durante 20 minutos, remueve suavemente, añade los tomates cherry enteros y hornea otros 10 minutos hasta que las verduras adquieran bordes dorados y tiernos. Retira del horno y deja atemperar.

### Paso 2: Cocción de la Pasta
Mientras las verduras se doran en el horno, pon a hervir una olla con abundante agua (1 litro por cada 100 g de pasta) y una cucharada de sal. Añade los fusilli y cocina el tiempo indicado en el paquete para conseguir un punto al dente firme. Escurre bien y vuelca en una ensaladera amplia, rociando un hilo fino de aceite para evitar que se pegue.

### Paso 3: Emulsión del Aliño
En un tarro pequeño con tapa o en un bol hondo, combina el AOVE, el vinagre de manzana, la mostaza de Dijon, la miel, una pizca de sal, pimienta y la albahaca fresca picada. Agita vigorosamente hasta lograr una vinagreta ligada, fragante y brillante.

### Paso 4: Mezcla y Montaje de la Ensalada
Incorpora las verduras asadas templadas a la ensaladera con la pasta. Añade las aceitunas negras cortadas en rodajas y el queso feta desmenuzado en trozos rústicos. Vierte el aliño de albahaca por encima y remueve suavemente con dos cucharas de madera para que todos los ingredientes queden bañados de manera homogénea.

### Paso 5: Reposo y Presentación
Deja reposar la ensalada durante 15 minutos a temperatura ambiente para que los sabores de las hortalizas asadas se fundan con la pasta y el aliño. Decora con unas hojas tiernas de albahaca fresca entera antes de servir en la mesa.

---

## Consejos de Conservación y Variantes

Esta ensalada aguanta en perfecto estado hasta 3 días en la nevera conservada en un recipiente hermético de cristal. Si vas a llevarla en táper, reserva el queso y unas cucharadas extra de aliño para incorporarlos justo en el momento de degustar. Para una versión con mayor aporte proteico, puedes enriquecerla con dados de pechuga de pollo a la plancha, garbanzos cocidos crujientes o lascas de atún en aceite de oliva.

---

## Preguntas Frecuentes sobre la Ensalada de Pasta con Verduras Asadas

### ¿Se debe servir esta ensalada fría de la nevera o templada?
Se disfruta al máximo templada o a temperatura ambiente. Si ha estado refrigerada en la nevera, es muy recomendable sacarla unos 20 minutos antes de consumir para que el aceite de oliva recupere su fluidez y las verduras desplieguen todo su buqué aromático.

### ¿Qué hacer si las verduras sueltan demasiada agua en el horno?
Para evitar que las verduras se cuezan en su propio vapor en vez de dorarse, asegúrate de no abarrotar la bandeja de horno y utiliza una temperatura firme de 200 °C. Si es necesario, reparte las hortalizas en dos bandejas independientes.

### ¿Se pueden preparar las verduras asadas con antelación?
Totalmente. Puedes asar una gran bandeja de verduras el domingo durante tu sesión de batch cooking y conservarlas en el frigorífico. Así, solo tendrás que cocer la pasta y montar el plato en apenas 10 minutos.
"""

article_payload = {
    "title": "Ensalada de Pasta con Verduras Asadas: Receta Saludable y Fácil",
    "slug": "ensalada-de-pasta-con-verduras-asadas",
    "excerpt": "Aprende a preparar una deliciosa ensalada de pasta con verduras asadas al horno, queso feta y vinagreta de albahaca: sana, completa y llena de sabor.",
    "category": "Ensaladas",
    "content_markdown": content_markdown,
    "chef_tip": "Asa las verduras a 200 °C en una sola capa bien esparcidas para que se doren y caramelicen en sus propios jugos sin reblandecerse ni soltar agua en exceso.",
    "image_alt": "Ensalada de pasta con verduras asadas al horno pimientos calabacin cebolla y queso feta en cuenco rustico",
    "image_negative_prompt": "text, watermark, logo, blurry, messy, raw vegetables, unappetizing, saturated artificial colors",
    "hero_image_prompt": "A vibrant Mediterranean pasta salad with roasted oven-caramelized vegetables zucchini red bell pepper cherry tomatoes red onion and crumbled feta cheese, served in a rustic ceramic bowl, garnished with fresh basil leaves, extra virgin olive oil drizzle, natural daylight, food photography, 8k, photorealistic",
    "pinterest_pin_prompt": "A mouthwatering vertical 2:3 shot of an artisanal bowl filled with spiral pasta and colorful roasted vegetables with melted feta crumbs and fresh basil, warm sunny kitchen atmosphere, culinary food photography",
    "recipe_schema": {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": "Ensalada de Pasta con Verduras Asadas",
        "description": "Receta mediterránea y saludable de ensalada de pasta con verduras asadas al horno, queso feta y una vinagreta aromática de albahaca fresca.",
        "image": "https://hokcljsrrnjxzgdhjice.supabase.co/storage/v1/object/public/recipe-images/recetagenial/ensalada-de-pasta-con-verduras-asadas-hero.jpg",
        "author": {
            "@type": "Person",
            "name": "Equipo Receta Genial"
        },
        "prepTime": "PT15M",
        "cookTime": "PT30M",
        "totalTime": "PT45M",
        "recipeYield": "4 raciones",
        "recipeCuisine": "Española",
        "recipeCategory": "Ensaladas",
        "recipeIngredient": [
            "350 g de pasta corta de trigo duro (fusilli o penne)",
            "1 calabacín mediano cortado en dados de 2 cm",
            "1 berenjena pequeña cortada en cubos",
            "1 pimiento rojo carnoso en trozos regulares",
            "1 pimiento amarillo en dados",
            "1 cebolla morada cortada en gajos",
            "150 g de tomates cherry enteros",
            "60 g de aceitunas negras deshuesadas",
            "120 g de queso feta desmenuzado",
            "50 ml de aceite de oliva virgen extra para el aliño",
            "15 ml de vinagre de manzana o balsámico suave",
            "1 cucharadita de mostaza antigua de Dijon",
            "Hojas de albahaca fresca picadas y orégano seco"
        ],
        "recipeInstructions": [
            {
                "@type": "HowToStep",
                "text": "Precalentar el horno a 200 °C. Disponer en una bandeja el calabacín, berenjena, pimientos y cebolla morada, rociar con aceite de oliva, sal, pimienta y orégano, y hornear 20 minutos."
            },
            {
                "@type": "HowToStep",
                "text": "Añadir los tomates cherry a la bandeja de verduras y hornear 10 minutos adicionales hasta que las hortalizas estén tiernas y caramelizadas en los bordes."
            },
            {
                "@type": "HowToStep",
                "text": "Cocer la pasta corta en abundante agua hirviendo con sal hasta alcanzar el punto al dente. Escurrir bien y mezclar con un hilo de aceite de oliva en una ensaladera grande."
            },
            {
                "@type": "HowToStep",
                "text": "Preparar la vinagreta emulsionando el AOVE, vinagre de manzana, mostaza de Dijon, sal, pimienta y albahaca fresca picada en un cuenco pequeño."
            },
            {
                "@type": "HowToStep",
                "text": "Incorporar las verduras asadas templadas a la pasta, añadir las aceitunas negras y el queso feta desmenuzado."
            },
            {
                "@type": "HowToStep",
                "text": "Regar con la vinagreta de albahaca, mezclar suavemente y dejar reposar 15 minutos a temperatura ambiente antes de degustar."
            }
        ]
    },
    "faq_schema": [
        {
            "question": "¿Se debe servir esta ensalada fría de la nevera o templada?",
            "answer": "Se disfruta al máximo templada o a temperatura ambiente. Si ha estado refrigerada, déjala reposar 20 minutos antes de servir para reactivar los aromas del aceite y las verduras."
        },
        {
            "question": "¿Qué hacer si las verduras sueltan demasiada agua en el horno?",
            "answer": "Evita amontonar las verduras en la bandeja para que se doren en lugar de cocerse al vapor y asegúrate de mantener el horno a 200 °C."
        },
        {
            "question": "¿Se pueden preparar las verduras asadas con antelación?",
            "answer": "Sí, puedes asar las verduras con hasta 3 días de antelación y guardarlas en un recipiente hermético en la nevera listas para mezclar con la pasta recién cocida."
        }
    ]
}

res = validate_article_quality(json.dumps(article_payload))
print("Ensalada validation score:", res.get("score"), "Passed:", res.get("passed"), "Issues:", res.get("issues"))

out_path = PROJECT_ROOT / "data" / "runtime" / "ensalada_pasta_payload.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(article_payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("Saved payload to:", out_path)
