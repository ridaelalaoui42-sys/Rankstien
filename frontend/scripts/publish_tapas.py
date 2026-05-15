"""Publish 5 Tapas & Pinchos articles to Supabase with images."""
import requests
import json
from pathlib import Path

SUPABASE_URL = "https://xjvmnmfczvwkjiasirsl.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhqdm1ubWZjenZ3a2ppYXNpcnNsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODIwNjgxMywiZXhwIjoyMDkzNzgyODEzfQ.LWI7MaXTdR5Ma1rdvaCtUrDL-C0rNefro5Qj16QIy0o"
BUCKET = "recipe-images"
PROJECT_DIR = Path(__file__).parent.parent

HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
           "Content-Type": "application/json", "Prefer": "return=representation"}

LOCAL_IMAGES = {
    "patatas-bravas-receta-clasica":    "public/images/tapas/tapas-patatas-bravas.jpg",
    "gambas-al-ajillo-receta-espanola": "public/images/tapas/tapas-gambas-ajillo.jpg",
    "pan-con-tomate-receta-catalana":   "public/images/tapas/tapas-pan-con-tomate.jpg",
    "tortilla-espanola-perfecta":       "public/images/tapas/tapas-tortilla-espanola.jpg",
    "croquetas-de-jamon-iberico":       "public/images/tapas/tapas-croquetas-jamon.jpg",
}

def upload_image(slug, local_path):
    filename = f"tapas/{slug}.jpg"
    full = PROJECT_DIR / local_path
    if not full.exists():
        print(f"  Missing: {full}"); return None
    with open(full, "rb") as f:
        r = requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{filename}",
            headers={"Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "image/jpeg", "x-upsert": "true"},
            data=f)
    if r.status_code in [200, 201]:
        url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{filename}"
        print(f"  Image: {url}"); return url
    print(f"  Upload failed {r.status_code}: {r.text[:100]}"); return None

def upsert(post):
    ep = f"{SUPABASE_URL}/rest/v1/posts"
    check = requests.get(f"{ep}?slug=eq.{post['slug']}", headers=HEADERS)
    if check.status_code == 200 and check.json():
        r = requests.patch(f"{ep}?slug=eq.{post['slug']}", headers=HEADERS, json=post)
        print(f"  Updated ({r.status_code}): {post['slug']}")
    else:
        r = requests.post(ep, headers=HEADERS, json=post)
        print(f"  Inserted ({r.status_code}): {post['slug']}")
        if r.status_code not in [200, 201]: print(f"  ERROR: {r.text[:300]}")

ARTICLES = [
{
  "slug": "patatas-bravas-receta-clasica",
  "title": "Patatas Bravas: La Receta Clásica con Salsa Perfecta",
  "category": "Tapas & Pinchos",
  "status": "published",
  "excerpt": "Las patatas bravas más crujientes de tu vida, con la auténtica salsa brava picante y alioli casero. La tapa española más popular.",
  "content": """## La Tapa más Icónica de España\n\nLas **patatas bravas** son la tapa española por excelencia. En cada bar de España las encontrarás, pero pocas se hacen de verdad bien. El secreto está en la triple cocción de la patata y en una salsa brava con el punto picante exacto.\n\n## Ingredientes (4 personas)\n\n**Para las patatas:**\n- 800g de patatas para freír (Monalisa o Kennebec)\n- Aceite de oliva abundante para freír\n- Sal gruesa\n\n**Para la salsa brava:**\n- 4 cucharadas de aceite de oliva virgen extra\n- 4 dientes de ajo picados\n- 1 cebolla pequeña picada\n- 1 cucharada de pimentón dulce\n- 1 cucharadita de pimentón picante\n- 200ml de tomate triturado\n- 1 cucharadita de vinagre de jerez\n- Sal y pimienta\n\n**Para el alioli:**\n- 1 huevo entero\n- 1 diente de ajo\n- 200ml aceite de girasol\n- Sal y limón\n\n## Paso a Paso\n\n### 1. Patatas en Triple Cocción\nPela y corta las patatas en dados irregulares de 3cm. **Primera cocción:** cuécelas en agua con sal 8 minutos, escurre y seca bien. **Segunda:** fríe a 140°C durante 6 minutos (quedan blandas). Escurre en papel. **Tercera:** sube el aceite a 190°C y fríe 2-3 minutos hasta que estén doradas y crujientes.\n\n### 2. Salsa Brava\nSofrié el ajo y la cebolla en aceite a fuego medio hasta transparente. Añade los pimentones y cocina 1 minuto. Agrega el tomate, sal, pimienta y el vinagre. Cocina 15 minutos. Tritura con batidora hasta conseguir una salsa lisa.\n\n### 3. Alioli Casero\nEn un vaso de batidora, pon el huevo, el ajo, sal y el aceite. Introduce el brazo de la batidora hasta el fondo y bate sin mover hasta que emulsione. Luego mueve suavemente hacia arriba.\n\n### 4. Montaje\nColoca las patatas en cazuela de barro. Napea con la salsa brava caliente y añade el alioli a temperatura ambiente. Sirve inmediatamente.\n\n## Tips de Chef\n\n- **La clave es el secado**: las patatas deben estar completamente secas antes de la segunda fritura o salpica.\n- **Aceite de sabor neutro**: para la fritura mezcla mitad oliva suave / mitad girasol.\n- **La salsa**: en Madrid la hacen sin tomate (solo pimentón, caldo y harina). La versión con tomate es más moderna.\n\n## Variaciones Regionales\n\n- **Madrid**: Salsa sin tomate, base de harina tostada con pimentón\n- **Barcelona**: Con alioli solo, sin salsa picante\n- **Sevilla**: Con mayonesa y kétchup mezclados (la versión más informal)\n""",
  "meta_title": "Patatas Bravas Receta Clásica con Salsa Perfecta | RecetaDolce",
  "meta_description": "Receta auténtica de patatas bravas crujientes con salsa brava casera y alioli. Triple cocción para máxima textura. La tapa española más famosa.",
  "keywords": ["patatas bravas","receta patatas bravas","salsa brava","tapas españolas"],
  "recipe_schema": json.dumps({"prepTime":"20 min","cookTime":"30 min","totalTime":"50 min","servings":4,"calories":"380 kcal","difficulty":"Media","ingredients":["800g patatas","200ml tomate triturado","pimentón dulce y picante","4 dientes ajo","1 huevo","aceite oliva"],"instructions":["Triple cocción de patatas","Preparar salsa brava","Hacer alioli casero","Montar y servir"],"nutrition":{"calories":"380 kcal","protein":"6g","carbs":"45g","fat":"19g"}}),
  "faq_schema": json.dumps([{"question":"¿Cuál es el secreto de las patatas bravas crujientes?","answer":"La triple cocción: hervir, freír a baja temperatura y freír a alta temperatura. El secado completo antes de cada fritura es fundamental."},{"question":"¿La salsa brava lleva tomate?","answer":"Depende de la región. La receta madrileña tradicional no lleva tomate, solo pimentón, harina y caldo. La versión moderna sí lleva tomate."}]),
},
{
  "slug": "gambas-al-ajillo-receta-espanola",
  "title": "Gambas al Ajillo: La Receta Española Perfecta en 10 Minutos",
  "category": "Tapas & Pinchos",
  "status": "published",
  "excerpt": "Gambas al ajillo auténticas en cazuela de barro: gambas jugosas en aceite de ajo y guindilla, listas en 10 minutos. La tapa favorita de España.",
  "content": """## El Ritual de la Cazuela Humeante\n\nLas **gambas al ajillo** son mucho más que una tapa. Son un ritual: la cazuela llega a la mesa chisporroteando, con el aroma del ajo dorado y el aceite de oliva impregnando el aire. El secreto es la temperatura y la calidad de las gambas.\n\n## Ingredientes (2 personas como tapa)\n\n- 300g de gambas medianas peladas (frescas o descongeladas en nevera)\n- 8 dientes de ajo laminados\n- 2 guindillas cayenas secas (o al gusto)\n- 100ml de aceite de oliva virgen extra (generoso)\n- 1 cucharada de vino blanco seco (opcional)\n- Sal marina\n- Perejil fresco picado\n- Pan rústico para acompañar\n\n## Paso a Paso\n\n### 1. Preparación\nSi las gambas están congeladas, descongélalas en nevera la noche anterior y sécalas bien con papel de cocina. El agua es el enemigo del ajillo.\n\n### 2. Infusión del Aceite\nEn una cazuela de barro (fundamental para el calor uniforme) calienta el aceite a fuego medio. Añade el ajo laminado y las guindillas. Cocina **muy lentamente** hasta que el ajo empiece a dorarse sin quemarse, 3-4 minutos.\n\n### 3. Las Gambas\nSube el fuego a alto. Añade las gambas, una pizca de sal y el vino blanco. Saltea 1-2 minutos exactos — las gambas deben quedar jugosas, no gomosas. En el momento en que cambien de color, retira del fuego.\n\n### 4. Servir\nEspolvorea perejil picado y lleva a la mesa inmediatamente mientras aún chisporrotea. Sirve con pan de pueblo para mojar en el aceite.\n\n## Tips de Chef\n\n- **El ajo**: Laminado fino se dora más rápido y aporta más sabor que picado.\n- **Temperatura**: Las gambas necesitan calor muy fuerte y tiempo muy corto. A fuego bajo quedan gomosas.\n- **Cazuela de barro**: Retiene el calor y sigue cocinando cuando la llevas a la mesa — factor en cuenta.\n- **Calidad**: Con gambas de calidad y buen aceite de oliva, no hace falta nada más.\n\n## Variaciones\n\n- **Con langostinos**: Más grandes, necesitan 30 segundos más\n- **Con gambas congeladas**: Funcionan perfectamente si se descongelan lentamente\n- **Versión con jerez**: Sustituye el vino blanco por jerez fino\n""",
  "meta_title": "Gambas al Ajillo Receta Española Perfecta 10 Minutos | RecetaDolce",
  "meta_description": "Receta auténtica de gambas al ajillo en cazuela de barro. Gambas jugosas en aceite de ajo y guindilla. Lista en 10 minutos. La tapa española más clásica.",
  "keywords": ["gambas al ajillo","receta gambas al ajillo","tapas gambas","gambas ajo"],
  "recipe_schema": json.dumps({"prepTime":"5 min","cookTime":"10 min","totalTime":"15 min","servings":2,"calories":"290 kcal","difficulty":"Fácil","ingredients":["300g gambas peladas","8 dientes ajo","2 guindillas","100ml aceite oliva virgen extra","perejil fresco"],"instructions":["Secar gambas","Infusionar aceite con ajo y guindilla","Saltear gambas 2 min a fuego alto","Servir inmediatamente"],"nutrition":{"calories":"290 kcal","protein":"24g","carbs":"3g","fat":"20g"}}),
  "faq_schema": json.dumps([{"question":"¿Cuánto tiempo se cocinan las gambas al ajillo?","answer":"Exactamente 1-2 minutos a fuego muy alto. En el momento en que cambian de color gris a rosa/naranja, están listas. Si se pasan, quedan gomosas."},{"question":"¿Es necesaria la cazuela de barro?","answer":"No es imprescindible pero sí muy recomendable. El barro retiene el calor mejor y le da el sabor y la presentación tradicional."}]),
},
{
  "slug": "pan-con-tomate-receta-catalana",
  "title": "Pan con Tomate Catalán: La Receta Original Pa amb Tomàquet",
  "category": "Tapas & Pinchos",
  "status": "published",
  "excerpt": "El auténtico pa amb tomàquet catalán con pan de cristal, tomate de colgar y aceite de oliva virgen extra. Sencillo, perfecto e irresistible.",
  "content": """## El Desayuno y la Tapa de Cataluña\n\nEl **pan con tomate** (pa amb tomàquet en catalán) es el plato más representativo de la cocina catalana. No es una tosta, no es un bruschetta — es algo único. La combinación de pan de cristal tostado, tomate frotado y aceite de oliva es explosiva en su sencillez.\n\n## Ingredientes (4 personas)\n\n- 4 rebanadas gruesas de pan de cristal (o pan de payés, chapata)\n- 2 tomates maduros de colgar (o tomates de pera muy maduros)\n- 1 diente de ajo (opcional, para los que gustan el toque fuerte)\n- Aceite de oliva virgen extra de calidad (Arbequina o Picual)\n- Sal marina en escamas (Maldon)\n\n**Para acompañar:**\n- Jamón ibérico / jamón serrano\n- Anchoas en aceite\n- Queso de cabra\n\n## Paso a Paso\n\n### 1. El Pan\nEl pan debe estar tostado — ligeramente si es pan fresco, más si es del día anterior. Usa una tostadora, parrilla o plancha. El pan debe tener costra firme para resistir el tomate.\n\n### 2. El Ajo (opcional)\nFrota el diente de ajo por la superficie del pan tostado con movimientos firmes. Solo si te gusta el sabor del ajo — hay puristas que no lo ponen.\n\n### 3. El Tomate\nCorta el tomate por la mitad (horizontalmente). Frota el tomate sobre el pan con presión circular, exprimiendo el jugo y la pulpa. El tomate debe dejar una capa rojiza húmeda. Desecha la piel.\n\n### 4. Aceite y Sal\nRocía generosamente con aceite de oliva virgen extra de calidad. Añade sal en escamas justo antes de servir.\n\n## El Debate del Pan de Cristal\n\nEl **pan de cristal** es la variedad catalana ideal para el pa amb tomàquet: masa muy hidratada, interior abierto y poroso que absorbe el tomate, costra fina y crujiente. Si no encuentras pan de cristal, una buena chapata o un pan de payés son las mejores alternativas.\n\n## Tips de Chef\n\n- **El tomate**: Debe estar muy maduro — casi pasado. El tomate de colgar catalán es el ideal.\n- **El aceite**: No escatimes. Un buen aceite de oliva virgen extra es el 50% del plato.\n- **El orden**: Primero ajo (si usas), luego tomate, luego aceite, luego sal. Nunca al revés.\n- **Servir inmediato**: El pan se reblandece rápido. Hazlo y sírvelo.\n""",
  "meta_title": "Pan con Tomate Catalán Receta Original Pa amb Tomàquet | RecetaDolce",
  "meta_description": "Receta auténtica del pan con tomate catalán (pa amb tomàquet). Con pan de cristal, tomate de colgar y aceite de oliva virgen extra. Sencillo y perfecto.",
  "keywords": ["pan con tomate","pa amb tomàquet","pan tomate catalán","tapa catalana"],
  "recipe_schema": json.dumps({"prepTime":"5 min","cookTime":"3 min","totalTime":"8 min","servings":4,"calories":"180 kcal","difficulty":"Fácil","ingredients":["4 rebanadas pan cristal","2 tomates maduros","aceite oliva virgen extra","sal en escamas","1 diente ajo opcional"],"instructions":["Tostar el pan","Frotar ajo opcional","Frotar tomate con presión","Añadir aceite generoso y sal"],"nutrition":{"calories":"180 kcal","protein":"4g","carbs":"28g","fat":"6g"}}),
  "faq_schema": json.dumps([{"question":"¿Qué pan es mejor para el pan con tomate?","answer":"El pan de cristal catalán es el original. En su defecto, una buena chapata o pan de payés con corteza firme."},{"question":"¿Se puede preparar el pan con tomate con antelación?","answer":"No. El pan se reblandece en minutos con el jugo del tomate. Prepáralo y sírvelo inmediatamente."}]),
},
{
  "slug": "tortilla-espanola-perfecta",
  "title": "Tortilla Española Perfecta: Jugosa por Dentro y Dorada por Fuera",
  "category": "Tapas & Pinchos",
  "status": "published",
  "excerpt": "La tortilla española perfecta: jugosa y cremosa por dentro (jugosa), dorada por fuera. Técnica paso a paso con todos los secretos de los maestros.",
  "content": """## El Debate Eterno: ¿Con o Sin Cebolla?\n\nLa **tortilla española** es el plato más debatido de la gastronomía española. ¿Con cebolla o sin? ¿Jugosa o cuajada? ¿Aceite de oliva o girasol? Aquí te damos la receta que satisface a todos: jugosa en el centro, perfectamente dorada fuera.\n\n## Ingredientes (sartén de 22cm, 4-6 personas)\n\n- 6 huevos XL frescos (temperatura ambiente)\n- 500g de patatas (Monalisa o Kennebec)\n- 1 cebolla mediana (opcional pero recomendada)\n- 150ml de aceite de oliva suave\n- Sal fina\n\n## Paso a Paso\n\n### 1. Las Patatas y la Cebolla\nPela y corta las patatas en rodajas finas irregulares (no en dados). La cebolla en juliana fina. Calienta el aceite en la sartén a fuego medio-bajo. Añade patatas y cebolla con sal. Confita (no fríe) a fuego suave 20-25 minutos, removiendo ocasionalmente, hasta que estén tiernas y ligeramente doradas.\n\n### 2. Los Huevos\nBate los huevos en un bol grande con sal hasta que estén bien integrados. Escurre las patatas y la cebolla del aceite (guarda el aceite) y mézclalas con los huevos batidos. Presiona un poco para que los huevos envuelvan bien la patata. Deja reposar 5 minutos.\n\n### 3. El Cuajado\nEn la sartén limpia, pon 2 cucharadas del aceite reservado a fuego medio-alto. Cuando esté caliente, vierte la mezcla. Baja a fuego medio. Con una espátula, mueve los bordes hacia dentro durante 2 minutos. Cuando los bordes estén cuajados pero el centro aún líquido, es el momento de dar la vuelta.\n\n### 4. El Volteo\nCubre la sartén con un plato grande (más grande que la sartén). Con un movimiento firme y decidido, voltea la tortilla sobre el plato. Desliza de nuevo a la sartén por el lado crudo. Cocina 1-2 minutos más. Repite si quieres más cuajado.\n\n### 5. El Reposo\nDeja reposar la tortilla fuera del fuego 3-5 minutos antes de servir. Se puede comer caliente, templada o fría — todas las temperaturas son válidas.\n\n## Tips de Chef\n\n- **Los huevos**: Temperatura ambiente emulsionan mejor.\n- **El aceite**: Abundante para confitar, no para freír. Es la diferencia entre tortilla y tortilla-omelette.\n- **El volteo**: El único momento de verdad. Sartén antiadherente de calidad y decisión.\n- **El punto jugoso**: Si cuajas mucho el centro, pierdes la textura cremosa característica.\n""",
  "meta_title": "Tortilla Española Perfecta Jugosa y Dorada | RecetaDolce",
  "meta_description": "Receta de tortilla española perfecta: jugosa por dentro y dorada por fuera. Técnica paso a paso con todos los secretos para el volteo y punto ideal.",
  "keywords": ["tortilla española","tortilla de patatas","receta tortilla española","tortilla jugosa"],
  "recipe_schema": json.dumps({"prepTime":"15 min","cookTime":"30 min","totalTime":"45 min","servings":6,"calories":"320 kcal","difficulty":"Media","ingredients":["6 huevos XL","500g patatas","1 cebolla","150ml aceite oliva suave","sal"],"instructions":["Confitar patatas y cebolla 25min","Mezclar con huevos batidos y reposar","Cuajar a fuego medio-alto","Voltear con plato","Reposar 5 min"],"nutrition":{"calories":"320 kcal","protein":"12g","carbs":"22g","fat":"21g"}}),
  "faq_schema": json.dumps([{"question":"¿Con o sin cebolla la tortilla española?","answer":"Es cuestión de gusto. Con cebolla queda más dulce y jugosa. Sin cebolla, el sabor de patata y huevo es más puro. Ambas versiones son auténticas."},{"question":"¿Por qué se rompe la tortilla al voltearla?","answer":"Generalmente porque los bordes no están suficientemente cuajados antes del volteo, o porque la sartén no es antiadherente de calidad."}]),
},
{
  "slug": "croquetas-de-jamon-iberico",
  "title": "Croquetas de Jamón Ibérico: La Receta Definitiva Paso a Paso",
  "category": "Tapas & Pinchos",
  "status": "published",
  "excerpt": "Croquetas de jamón ibérico con bechamel cremosa, rebozado crujiente perfecto y el sabor inconfundible del jamón. La tapa española más querida.",
  "content": """## La Tapa más Querida de España\n\nLas **croquetas de jamón** son el símbolo de la cocina española casera. Una bechamel perfecta, jugosa, con trozos generosos de jamón ibérico, rebozadas con una capa crujiente dorada. El secreto es tiempo, paciencia y buena materia prima.\n\n## Ingredientes (25-30 croquetas)\n\n**Para la bechamel:**\n- 100g de mantequilla\n- 100g de harina de trigo\n- 800ml de leche entera caliente\n- 150g de jamón ibérico en taquitos pequeños\n- 1/2 cebolla muy picada\n- Nuez moscada, sal, pimienta blanca\n\n**Para el rebozado:**\n- 2 huevos batidos\n- Pan rallado fino (o panko para más crujiente)\n- Aceite abundante para freír\n\n## Paso a Paso\n\n### 1. La Base de la Bechamel\nEn una cazuela ancha, sofríe la cebolla en la mantequilla a fuego muy suave hasta transparente (5 min). Añade el jamón y saltea 1 minuto — el calor potencia su sabor. Incorpora la harina de golpe y cocina 2-3 minutos removiendo constantemente (el roux no debe coger color).\n\n### 2. Incorporar la Leche\nAñade la leche caliente poco a poco, removiendo sin parar con varillas. Cuando esté toda incorporada, cocina a fuego medio-bajo **mínimo 20 minutos**, removiendo con frecuencia. La masa debe despegarse de las paredes. Añade nuez moscada, rectifica sal.\n\n### 3. Reposo en Frío\nExtiende la masa en una bandeja plana untada con mantequilla. Cubre con film a contacto (tocando la masa) para evitar costra. Refrigera **mínimo 4 horas**, idealmente toda la noche.\n\n### 4. Formar las Croquetas\nCon una cuchara o manga, forma porciones. Moldea con las manos enharinadas en forma ovalada. Pasa por huevo batido y luego por pan rallado, presionando para que se adhiera. Refrigera 30 minutos más antes de freír.\n\n### 5. Freír\nFríe en aceite abundante a 180°C en tandas pequeñas. 2-3 minutos hasta dorado uniforme. No pongas demasiadas — baja la temperatura del aceite. Escurre en papel absorbente. Sirve inmediatamente.\n\n## Tips de Chef\n\n- **La cocción larga de la bechamel**: 20 minutos mínimo para que pierda el sabor a harina cruda.\n- **El frío**: La masa bien fría es más fácil de manejar y las croquetas mantienen mejor la forma.\n- **Panko**: El pan rallado japonés da más crujiente que el español convencional.\n- **Temperatura del aceite**: A 180°C exactos. Menos temperatura = absorben grasa. Más = se queman fuera y frías dentro.\n""",
  "meta_title": "Croquetas de Jamón Ibérico Receta Definitiva | RecetaDolce",
  "meta_description": "Receta definitiva de croquetas de jamón ibérico con bechamel cremosa y rebozado crujiente. Todos los secretos paso a paso para croquetas perfectas.",
  "keywords": ["croquetas de jamón","receta croquetas jamón","croquetas ibéricas","tapas croquetas"],
  "recipe_schema": json.dumps({"prepTime":"30 min","cookTime":"30 min","totalTime":"60 min + 4h frío","servings":28,"calories":"95 kcal","difficulty":"Media","ingredients":["100g mantequilla","100g harina","800ml leche entera","150g jamón ibérico","2 huevos","pan rallado"],"instructions":["Sofreír cebolla y jamón","Añadir harina y leche poco a poco","Cocer bechamel 20min","Enfriar 4h mínimo","Formar y rebozan","Freír a 180°C"],"nutrition":{"calories":"95 kcal","protein":"4g","carbs":"8g","fat":"5g"}}),
  "faq_schema": json.dumps([{"question":"¿Por qué se abren las croquetas al freír?","answer":"Porque la masa estaba caliente, el rebozado no estaba bien sellado, o el aceite no estaba a la temperatura correcta (180°C)."},{"question":"¿Se pueden congelar las croquetas?","answer":"Sí, perfectamente. Congélalas ya rebozadas en una bandeja (sin que se toquen) y luego pásalas a bolsa. Fríelas directamente del congelador a 170°C."}]),
},
]

def main():
    print("RecetaDolce — Tapas & Pinchos Publisher")
    print("=" * 45)
    for art in ARTICLES:
        n = ARTICLES.index(art) + 1
        print(f"\n[{n}/5] {art['title'][:65]}")
        local = LOCAL_IMAGES.get(art["slug"])
        if local:
            img_url = upload_image(art["slug"], local)
            if img_url:
                art["featured_image"] = img_url
        upsert(art)
    print("\nDone!")

if __name__ == "__main__":
    main()
