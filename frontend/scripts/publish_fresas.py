"""Publish 5 fresas articles directly to Supabase (no AntigravityManager needed)."""
import requests
import json

SUPABASE_URL = "https://xjvmnmfczvwkjiasirsl.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhqdm1ubWZjenZ3a2ppYXNpcnNsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODIwNjgxMywiZXhwIjoyMDkzNzgyODEzfQ.LWI7MaXTdR5Ma1rdvaCtUrDL-C0rNefro5Qj16QIy0o"
BUCKET = "recipe-images"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

LOCAL_IMAGES = {
    "tarta-de-fresas-con-nata": "public/images/fresas/fresas-tarta-nata.jpg",
    "mermelada-de-fresas-casera": "public/images/fresas/fresas-mermelada-casera.jpg",
    "fresas-con-nata-perfectas": "public/images/fresas/fresas-con-nata.jpg",
    "mousse-de-fresa-mascarpone": "public/images/fresas/fresas-mousse-mascarpone.jpg",
    "batido-cremoso-de-fresas": "public/images/fresas/fresas-batido-cremoso.jpg",
}

def upload_image(slug, local_path):
    filename = f"fresas/{slug}.jpg"
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{filename}"
    try:
        with open(local_path, "rb") as f:
            r = requests.post(url, headers={"Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "image/jpeg", "x-upsert": "true"}, data=f)
        if r.status_code in [200, 201]:
            pub = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{filename}"
            print(f"  Image uploaded: {pub}")
            return pub
    except Exception as e:
        print(f"  Upload failed: {e}")
    return None

def upsert_post(post):
    ep = f"{SUPABASE_URL}/rest/v1/posts"
    check = requests.get(f"{ep}?slug=eq.{post['slug']}", headers=HEADERS)
    if check.status_code == 200 and check.json():
        r = requests.patch(f"{ep}?slug=eq.{post['slug']}", headers=HEADERS, json=post)
        print(f"  Updated: {post['slug']} ({r.status_code})")
    else:
        r = requests.post(ep, headers=HEADERS, json=post)
        print(f"  Inserted: {post['slug']} ({r.status_code})")
        if r.status_code not in [200, 201]:
            print(f"  ERROR: {r.text[:300]}")

ARTICLES = [
  {
    "slug": "tarta-de-fresas-con-nata",
    "title": "Tarta de Fresas con Nata: La Receta Clásica Española",
    "category": "Postres",
    "status": "published",
    "excerpt": "La tarta de fresas con nata es el postre español por excelencia. Aprende a prepararla con masa quebrada casera y fresas frescas de temporada.",
    "content": """## La Reina de los Postres Españoles\n\nLa **tarta de fresas con nata** es uno de los postres más queridos en España. Su combinación de masa quebrada crujiente, crema pastelera suave y fresas frescas brillantes la convierte en la protagonista de cualquier mesa.\n\n## Ingredientes\n\n- 300g de fresas frescas\n- 250ml de nata para montar (35% MG)\n- 2 cucharadas de azúcar glass\n- 1 base de masa quebrada (22cm)\n- 200ml de leche entera\n- 3 yemas de huevo\n- 50g de azúcar\n- 20g de maicena\n- 1 vaina de vainilla\n- Gelatina de fresas para brillo (opcional)\n\n## Paso a Paso\n\n### 1. Masa Quebrada\nHorna la base de masa quebrada a 180°C durante 15 minutos con papel y legumbres encima (cocción en blanco). Deja enfriar completamente.\n\n### 2. Crema Pastelera\nCalienta la leche con la vainilla. Bate las yemas con el azúcar y la maicena. Vierte la leche caliente poco a poco, regresa al fuego y remueve hasta espesar. Cubre con film y enfría.\n\n### 3. Nata Montada\nMonta la nata bien fría con el azúcar glass hasta obtener picos firmes.\n\n### 4. Montaje\nExtiende la crema pastelera sobre la base. Añade la nata montada. Coloca las fresas lavadas y cortadas en mitades formando círculos concéntricos. Pincela con gelatina de fresas para un acabado profesional.\n\n## Tips de Chef\n\n- **Fresas de temporada**: Usa fresas de primavera, son más dulces y aromáticas.\n- **Temperatura**: Todos los componentes deben estar bien fríos antes de montar.\n- **Brillo**: La gelatina no solo es estética, protege las fresas de oxidarse.\n\n## Variaciones\n\n- **Sin gluten**: Usa harina de arroz para la masa.\n- **Versión ligera**: Cambia parte de la nata por yogur griego.\n- **Con chocolate**: Añade una capa de ganache entre la masa y la crema.\n""",
    "meta_title": "Tarta de Fresas con Nata Clásica Española | RecetaDolce",
    "meta_description": "Aprende a hacer la tarta de fresas con nata perfecta. Receta española tradicional con masa quebrada, crema pastelera y fresas frescas de temporada.",
    "keywords": ["tarta de fresas", "tarta fresas con nata", "receta tarta fresas", "postre fresas"],
    "recipe_schema": json.dumps({"prepTime":"30 min","cookTime":"15 min","totalTime":"45 min","servings":8,"calories":"280 kcal","difficulty":"Media","ingredients":["300g fresas frescas","250ml nata montar","1 base masa quebrada","200ml leche","3 yemas","50g azúcar"],"instructions":["Hornear base 15min a 180°C","Preparar crema pastelera","Montar nata con azúcar glass","Montar tarta por capas","Decorar con fresas"],"nutrition":{"calories":"280 kcal","protein":"5g","carbs":"32g","fat":"14g"}}),
    "faq_schema": json.dumps([{"question":"¿Cuánto dura la tarta de fresas?","answer":"En nevera aguanta hasta 2 días. Es mejor consumirla el mismo día para que las fresas no suelten líquido."},{"question":"¿Puedo usar fresas congeladas?","answer":"Para decorar no, ya que pierden la textura. Sí puedes usarlas para la crema o el relleno."}]),
  },
  {
    "slug": "mermelada-de-fresas-casera",
    "title": "Mermelada de Fresas Casera Sin Pectina — Solo 3 Ingredientes",
    "category": "Postres",
    "status": "published",
    "excerpt": "Mermelada de fresas casera con solo fresas, azúcar y limón. Sin pectina añadida. Perfecta para tostar, yogures y repostería.",
    "content": """## La Mermelada más Fácil del Mundo\n\nHacer **mermelada de fresas casera** es más sencillo de lo que crees. Con solo 3 ingredientes y 30 minutos tienes un bote lleno de sabor auténtico, sin conservantes ni colorantes.\n\n## Ingredientes (para 2 botes de 250ml)\n\n- 1kg de fresas frescas maduras\n- 600g de azúcar blanco\n- Zumo de 1 limón grande\n\n## Paso a Paso\n\n### 1. Preparación\nLava y desinfecta los frascos en agua hirviendo. Limpia las fresas, quita el rabito y córtalas en trozos.\n\n### 2. Maceración (opcional pero recomendada)\nMezcla fresas y azúcar y deja reposar 2 horas o toda la noche. Sueltan su jugo y la mermelada queda más brillante.\n\n### 3. Cocción\nLleva a ebullición a fuego medio con el zumo de limón. Reduce a fuego bajo y cocina 25-30 minutos removiendo con frecuencia. Retira la espuma blanca que se forma.\n\n### 4. Prueba del Plato\nPon una cucharada en un plato frío. Si al inclinar el plato la mermelada se desliza lentamente, está lista.\n\n### 5. Envasado\nRellena los botes calientes, ciérralos y ponlos boca abajo 10 minutos para crear vacío natural.\n\n## Tips de Chef\n\n- **Ratio azúcar**: Para conservación óptima usa 60% del peso de las fresas en azúcar.\n- **El limón**: La pectina natural del limón ayuda a gelatinizar sin pectina industrial.\n- **Punto de mermelada**: Si tienes termómetro, 105°C es el punto exacto.\n\n## Variaciones\n\n- **Con vainilla**: Añade 1 vaina de vainilla durante la cocción.\n- **Con pimienta rosa**: Un toque gourmet para quesos y charcutería.\n- **Baja en azúcar**: Reduce a 400g pero consúmela en 2-3 semanas en nevera.\n""",
    "meta_title": "Mermelada de Fresas Casera Sin Pectina — 3 Ingredientes | RecetaDolce",
    "meta_description": "Receta fácil de mermelada de fresas casera sin pectina. Solo fresas, azúcar y limón. Lista en 30 minutos con técnica profesional.",
    "keywords": ["mermelada de fresas","mermelada fresas casera","mermelada sin pectina","conservas fresas"],
    "recipe_schema": json.dumps({"prepTime":"10 min","cookTime":"30 min","totalTime":"40 min","servings":32,"calories":"45 kcal","difficulty":"Fácil","ingredients":["1kg fresas frescas","600g azúcar","1 limón"],"instructions":["Lavar y cortar fresas","Macerar con azúcar 2h","Cocer 30min con limón","Envasar en caliente"],"nutrition":{"calories":"45 kcal","protein":"0g","carbs":"11g","fat":"0g"}}),
    "faq_schema": json.dumps([{"question":"¿Cuánto tiempo dura la mermelada casera?","answer":"Bien envasada al vacío dura 12 meses en un lugar fresco y oscuro. Una vez abierta, 3-4 semanas en nevera."},{"question":"¿Por qué se cristaliza la mermelada?","answer":"Por exceso de azúcar o cocción prolongada. Puedes corregirlo calentando el bote al baño maría."}]),
  },
  {
    "slug": "fresas-con-nata-perfectas",
    "title": "Fresas con Nata: Técnica y Secretos para Hacerlas Perfectas",
    "category": "Postres",
    "status": "published",
    "excerpt": "Las fresas con nata parecen sencillas pero tienen sus secretos. Descubre la técnica correcta para un resultado de restaurante en casa.",
    "content": """## El Postre más Español de la Temporada\n\nLas **fresas con nata** son el postre de temporada por excelencia en España. Pero entre unas fresas con nata mediocres y unas espectaculares hay una gran diferencia: la técnica y la calidad de los ingredientes.\n\n## Ingredientes (4 personas)\n\n- 600g de fresas de temporada\n- 400ml de nata para montar (mínimo 35% MG)\n- 3 cucharadas de azúcar glass (o al gusto)\n- 1 cucharadita de extracto de vainilla puro\n- Menta fresca para decorar\n- Una pizca de sal\n\n## El Secreto de la Nata Perfecta\n\n### Temperatura: La Clave\nLa nata, el bol y las varillas deben estar **muy fríos** — ponlos en el congelador 15 minutos antes. El frío es lo que permite que la nata monte correctamente.\n\n### Técnica de Montado\nEmpieza a velocidad baja e incrementa progresivamente. Para cuando veas picos medianos — la nata debe quedar **suave y cuchareable**, no apelmazada. La nata excesivamente montada pierde su textura sedosa.\n\n## Las Fresas\n\n- Escógelas brillantes, rojas hasta la punta y con perfume intenso.\n- Lávalas **antes** de quitar el rabito (nunca al revés, para que no absorban agua).\n- Córtalas justo antes de servir para evitar que se oxide.\n- Mácera con una cucharada de azúcar y unas gotas de limón 5 minutos para intensificar el sabor.\n\n## Montaje\n\n1. Coloca las fresas en el fondo del bol o copa\n2. Añade la nata con una cuchara o manga pastelera\n3. Decora con una hoja de menta y una fresa entera\n4. Sirve inmediatamente\n\n## Tips de Chef\n\n- **La sal**: Una pizca de sal en la nata realza todos los sabores.\n- **Azúcar glass vs blanquilla**: El glass se integra mejor y no da textura arenosa.\n- **Servicio**: Siempre en copa o bol frío.\n""",
    "meta_title": "Fresas con Nata Perfectas — Técnica y Secretos | RecetaDolce",
    "meta_description": "Cómo hacer fresas con nata perfectas. Técnica para montar nata correctamente, cómo elegir fresas y trucos de chef para un resultado espectacular.",
    "keywords": ["fresas con nata","cómo hacer fresas con nata","nata montada","postre fresas temporada"],
    "recipe_schema": json.dumps({"prepTime":"15 min","cookTime":"0 min","totalTime":"15 min","servings":4,"calories":"220 kcal","difficulty":"Fácil","ingredients":["600g fresas","400ml nata 35%","3 tbsp azúcar glass","1 tsp vainilla","menta fresca"],"instructions":["Enfriar bol y varillas 15min","Lavar y cortar fresas, macerar","Montar nata a velocidad creciente","Emplatar y servir"],"nutrition":{"calories":"220 kcal","protein":"3g","carbs":"18g","fat":"15g"}}),
    "faq_schema": json.dumps([{"question":"¿Por qué no monta la nata?","answer":"La nata debe tener mínimo 35% de materia grasa y estar muy fría. Si está a temperatura ambiente, no montará."},{"question":"¿Cuánto tiempo puedo guardar la nata montada?","answer":"Máximo 2 horas en nevera. Pasado ese tiempo empieza a perder consistencia."}]),
  },
  {
    "slug": "mousse-de-fresa-mascarpone",
    "title": "Mousse de Fresa con Mascarpone — Ligera y Aireada",
    "category": "Postres",
    "status": "published",
    "excerpt": "Mousse de fresa esponjosa con mascarpone y merengue italiano. Un postre elegante listo en 20 minutos que impresiona a todos.",
    "content": """## Un Postre de Restaurante en Casa\n\nEsta **mousse de fresa con mascarpone** tiene una textura increíblemente aireada y un sabor intenso a fresa fresca. El secreto está en la combinación del puré de fresa, el mascarpone cremoso y el merengue que aporta la ligereza característica de toda buena mousse.\n\n## Ingredientes (6 personas)\n\n- 400g de fresas frescas\n- 250g de mascarpone\n- 200ml de nata para montar\n- 3 claras de huevo\n- 100g de azúcar\n- 2 hojas de gelatina (4g)\n- Zumo de medio limón\n- Fresas y coulis para decorar\n\n## Paso a Paso\n\n### 1. Coulis de Fresa\nTritura 300g de fresas con el zumo de limón y 40g de azúcar. Pasa por colador fino. Reserva 4 cucharadas para decorar.\n\n### 2. Gelatina\nHidrata las hojas de gelatina en agua fría 5 minutos. Escurre y disuelve en 2 cucharadas del coulis caliente. Añade al resto del coulis.\n\n### 3. Base de Mascarpone\nBate el mascarpone hasta que quede cremoso. Incorpora el coulis con gelatina y mezcla suavemente.\n\n### 4. Merengue Suizo\nMonta las claras con el azúcar restante (60g) al baño maría hasta 60°C, luego bate fuera del fuego hasta obtener picos firmes y brillantes.\n\n### 5. Montaje de la Mousse\nMonta la nata a punto medio. Incorpora primero la nata al mascarpone con movimientos envolventes, luego el merengue en dos tandas. No sobre-mezcles para conservar el aire.\n\n### 6. Reposo\nReparte en copas y refrigera mínimo 3 horas.\n\n## Tips de Chef\n\n- **Gelatina**: Imprescindible para que la mousse aguante. Sin ella se licua.\n- **Merengue suizo**: Más estable que el merengue francés, ideal para mousses.\n- **Temperatura**: El coulis debe estar a temperatura ambiente antes de mezclar con el mascarpone frío.\n""",
    "meta_title": "Mousse de Fresa con Mascarpone Aireada y Ligera | RecetaDolce",
    "meta_description": "Receta de mousse de fresa con mascarpone ultraligera. Con gelatina y merengue suizo para una textura perfecta. Lista en 20 minutos más reposo.",
    "keywords": ["mousse de fresa","mousse fresas mascarpone","postre fresas frio","receta mousse"],
    "recipe_schema": json.dumps({"prepTime":"25 min","cookTime":"0 min","totalTime":"25 min + 3h reposo","servings":6,"calories":"310 kcal","difficulty":"Media","ingredients":["400g fresas","250g mascarpone","200ml nata","3 claras","100g azúcar","2 hojas gelatina"],"instructions":["Hacer coulis de fresa","Disolver gelatina en coulis","Mezclar mascarpone y coulis","Hacer merengue suizo","Incorporar nata y merengue","Refrigerar 3h"],"nutrition":{"calories":"310 kcal","protein":"6g","carbs":"22g","fat":"22g"}}),
    "faq_schema": json.dumps([{"question":"¿Puedo hacer la mousse sin gelatina?","answer":"Puedes, pero quedará más líquida. En ese caso sirve en copa y consume el mismo día."},{"question":"¿Se puede congelar la mousse de fresa?","answer":"Sí, aguanta hasta 1 mes en el congelador. Descongela en nevera 6 horas antes de servir."}]),
  },
  {
    "slug": "batido-cremoso-de-fresas",
    "title": "Batido Cremoso de Fresas Sin Lactosa — 3 Ingredientes",
    "category": "Postres",
    "status": "published",
    "excerpt": "Batido de fresas cremoso, sin lactosa y sin azúcar añadido. Listo en 5 minutos con solo fresas, leche de avena y plátano.",
    "content": """## El Batido de Fresas Definitivo\n\nEste **batido cremoso de fresas** es uno de los más fáciles y versátiles. Sin lactosa, sin azúcar añadido y listo en 5 minutos. El plátano congelado es el secreto para obtener esa textura gruesa y cremosa sin necesidad de helado.\n\n## Ingredientes (2 vasos)\n\n- 300g de fresas frescas o congeladas\n- 1 plátano maduro congelado\n- 300ml de leche de avena (o almendras)\n- 1 cucharada de miel o sirope de agave (opcional)\n- Hielo al gusto\n- Fresas y granola para decorar\n\n## Paso a Paso\n\n### 1. Preparación\nCongela el plátano pelado la noche anterior — esto es el truco para la textura cremosa. Lava y desinfecta las fresas. Si son congeladas, úsalas directamente.\n\n### 2. Triturar\nPon en la batidora: fresas, plátano congelado troceado y la mitad de la leche. Tritura a máxima potencia 30 segundos.\n\n### 3. Ajustar Textura\nAñade el resto de la leche poco a poco hasta obtener la consistencia deseada. Para más espesor, menos leche. Prueba y añade miel si necesita más dulzor.\n\n### 4. Servir\nSirve inmediatamente en vasos altos con hielo. Decora con una fresa en el borde, granola crujiente y un poco de menta.\n\n## Tips de Chef\n\n- **Plátano congelado**: Es el sustituto perfecto del helado — aporta cremosidad y dulzor natural.\n- **Fresas congeladas**: Hacen el batido más frío y espeso sin necesitar tanto hielo.\n- **Potencia de batidora**: A mayor potencia, más cremoso. Las batidoras de vaso tipo Vitamix son ideales.\n\n## Variaciones\n\n- **Proteico**: Añade 1 scoop de proteína de vainilla.\n- **Verde**: Incorpora un puñado de espinacas baby (no se notan pero suman nutrientes).\n- **Tropical**: Sustituye la mitad de las fresas por mango.\n""",
    "meta_title": "Batido Cremoso de Fresas Sin Lactosa — 3 Ingredientes | RecetaDolce",
    "meta_description": "Batido de fresas cremoso sin lactosa y sin azúcar añadido. Solo 3 ingredientes y 5 minutos. Receta saludable con plátano congelado.",
    "keywords": ["batido de fresas","batido fresas sin lactosa","smoothie fresas","batido fresas saludable"],
    "recipe_schema": json.dumps({"prepTime":"5 min","cookTime":"0 min","totalTime":"5 min","servings":2,"calories":"160 kcal","difficulty":"Fácil","ingredients":["300g fresas","1 plátano congelado","300ml leche avena","1 tbsp miel opcional"],"instructions":["Congelar plátano la noche anterior","Triturar fresas y plátano con leche","Ajustar consistencia","Servir con decoración"],"nutrition":{"calories":"160 kcal","protein":"3g","carbs":"36g","fat":"2g"}}),
    "faq_schema": json.dumps([{"question":"¿Puedo usar fresas congeladas?","answer":"Sí, de hecho es mejor. Las fresas congeladas hacen el batido más espeso y frío sin añadir hielo."},{"question":"¿Por qué el plátano debe estar congelado?","answer":"El plátano congelado se tritura de forma diferente al fresco, generando una textura cremosa similar al helado sin necesidad de lácteos."}]),
  }
]

def main():
    print("RecetaDolce — Fresas Article Publisher")
    print("=" * 45)
    for art in ARTICLES:
        print(f"\n[{ARTICLES.index(art)+1}/5] {art['title'][:60]}")
        # Upload image
        local = LOCAL_IMAGES.get(art["slug"])
        if local:
            img_url = upload_image(art["slug"], local)
            if img_url:
                art["featured_image"] = img_url
        # Publish
        upsert_post(art)
    print("\nDone! Check https://RecetaDolce.com")

if __name__ == "__main__":
    main()
