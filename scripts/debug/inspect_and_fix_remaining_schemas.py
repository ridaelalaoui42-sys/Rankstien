import os
import urllib.request
import json
import re

RG_URL = 'https://hokcljsrrnjxzgdhjice.supabase.co'
RG_KEY = 'os.getenv('RECETAGENIAL_SUPABASE_KEY', '')'
RD_URL = 'https://xjvmnmfczvwkjiasirsl.supabase.co'
RD_KEY = 'os.getenv('RECETADOLCE_SUPABASE_KEY', '')'

def get_post(url, key, slug):
    req = urllib.request.Request(
        f'{url}/rest/v1/posts?slug=eq.{slug}&select=id,slug,title,status,content,recipe_schema,featured_image',
        headers={'apikey': key, 'Authorization': f'Bearer {key}'}
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read().decode('utf-8'))
        return data[0] if data else None

def update_post_schema(url, key, post_id, recipe_schema):
    req = urllib.request.Request(
        f'{url}/rest/v1/posts?id=eq.{post_id}',
        headers={'apikey': key, 'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'Prefer': 'return=representation'},
        data=json.dumps({'recipe_schema': recipe_schema}).encode('utf-8'),
        method='PATCH'
    )
    with urllib.request.urlopen(req) as r:
        return r.status in (200, 204)

# 1. RecetaGenial: ensalada-de-garbanzos-con-queso-feta
p1 = get_post(RG_URL, RG_KEY, 'ensalada-de-garbanzos-con-queso-feta')
if p1:
    schema = p1.get('recipe_schema') or {}
    print("P1 current instructions:", schema.get('recipeInstructions'))
    # Extract instructions from content
    content = p1.get('content', '')
    # Check lines in content
    steps = [
        "Enjuagar y escurrir bien los garbanzos cocidos en un colador.",
        "Lavar y cortar los tomates cherry por la mitad, y picar el pepino en dados pequeños.",
        "Picar la cebolla morada finamente en juliana o dados.",
        "Cortar o desmenuzar el queso feta en dados medianos.",
        "En un bol grande, mezclar los garbanzos, tomates, pepino, cebolla y aceitunas negras.",
        "Preparar el aliño batiendo el aceite de oliva virgen extra, zumo de limón, orégano, sal y pimienta.",
        "Verter el aliño sobre la ensalada, incorporar el queso feta y mezclar con suavidad antes de servir."
    ]
    schema['recipeInstructions'] = [{"@type": "HowToStep", "text": s} for s in steps]
    if not schema.get('recipeIngredient'):
        schema['recipeIngredient'] = [
            "400 g de garbanzos cocidos",
            "150 g de queso feta",
            "1 taza de tomates cherry",
            "1 pepino mediano",
            "1/2 cebolla morada",
            "50 g de aceitunas negras",
            "3 cucharadas de aceite de oliva virgen extra",
            "1 cucharada de zumo de limón",
            "1 cucharadita de orégano seco",
            "Sal y pimienta al gusto"
        ]
    schema['name'] = p1['title']
    schema['@type'] = 'Recipe'
    update_post_schema(RG_URL, RG_KEY, p1['id'], schema)
    print("Updated p1 ensalada-de-garbanzos-con-queso-feta")

# 2. RecetaGenial: aperitivos-salados-faciles-deliciosos
p2 = get_post(RG_URL, RG_KEY, 'aperitivos-salados-faciles-deliciosos')
if p2:
    schema = p2.get('recipe_schema') or {}
    if not schema.get('recipeIngredient') or len(schema.get('recipeIngredient')) == 0:
        schema['recipeIngredient'] = [
            "1 lámina de masa de hojaldre",
            "100 g de jamón serrano o ibérico",
            "150 g de queso brie o semicurado",
            "100 g de champiñones frescos",
            "1 huevo batido para pincelar",
            "Semillas de sésamo para decorar",
            "Aceite de oliva virgen extra",
            "Sal y pimienta"
        ]
        schema['name'] = p2['title']
        schema['@type'] = 'Recipe'
        update_post_schema(RG_URL, RG_KEY, p2['id'], schema)
        print("Updated p2 aperitivos-salados-faciles-deliciosos")

# 3. RecetaGenial: aperitivos-salados-faciles-originales
p3 = get_post(RG_URL, RG_KEY, 'aperitivos-salados-faciles-originales')
if p3:
    schema = {
        "@type": "Recipe",
        "name": p3['title'],
        "recipeYield": "6 raciones",
        "prepTime": "PT15M",
        "cookTime": "PT20M",
        "totalTime": "PT35M",
        "recipeIngredient": [
            "1 lámina de hojaldre fresco",
            "1 lata de mejillones en escabeche",
            "100 g de queso crema",
            "50 g de queso parmesano rallado",
            "Tomates maduros para gazpacho",
            "Aceite de oliva virgen extra y sal"
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Preparar el paté triturando los mejillones con el queso crema."},
            {"@type": "HowToStep", "text": "Extender el hojaldre, espolvorear el queso parmesano, enrollar y cortar en rodajas para hornear a 200°C."},
            {"@type": "HowToStep", "text": "Triturar los tomates con aceite y sal para preparar los vasitos de gazpacho."},
            {"@type": "HowToStep", "text": "Emplatar los tres aperitivos combinando colores y texturas."}
        ]
    }
    update_post_schema(RG_URL, RG_KEY, p3['id'], schema)
    print("Updated p3 aperitivos-salados-faciles-originales")

# 4. RecetaGenial: tapas-espanolas-para-reuniones-con-amigos
p4 = get_post(RG_URL, RG_KEY, 'tapas-espanolas-para-reuniones-con-amigos')
if p4:
    schema = {
        "@type": "Recipe",
        "name": p4['title'],
        "recipeYield": "8 raciones",
        "prepTime": "PT20M",
        "cookTime": "PT30M",
        "totalTime": "PT50M",
        "recipeIngredient": [
            "4 patatas medianas para tortilla",
            "5 huevos camperos",
            "200 g de gambas peladas",
            "4 dientes de ajo y guindilla",
            "Pan de barra artesanal",
            "Aceite de oliva virgen extra y sal"
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Preparar una tortilla española clásica pochando las patatas y cuajando con los huevos."},
            {"@type": "HowToStep", "text": "Saltear las gambas con los ajos laminados y la guindilla en una cazuela de barro."},
            {"@type": "HowToStep", "text": "Tostar rebanadas de pan y montar tostas variadas con jamón y tomate."},
            {"@type": "HowToStep", "text": "Servir las tapas calientes en fuentes centrales para compartir."}
        ]
    }
    update_post_schema(RG_URL, RG_KEY, p4['id'], schema)
    print("Updated p4 tapas-espanolas-para-reuniones-con-amigos")

# 5. RecetaGenial: aperitivos-deliciosos-y-faciles-para-tus-cenas-con-amigos
p5 = get_post(RG_URL, RG_KEY, 'aperitivos-deliciosos-y-faciles-para-tus-cenas-con-amigos')
if p5:
    schema = {
        "@type": "Recipe",
        "name": p5['title'],
        "recipeYield": "6 raciones",
        "prepTime": "PT15M",
        "cookTime": "PT15M",
        "totalTime": "PT30M",
        "recipeIngredient": [
            "1 baguette de pan crujiente",
            "100 g de queso de cabra",
            "2 cucharadas de cebolla caramelizada",
            "100 g de salmón ahumado",
            "Queso de untar con eneldo",
            "Aceite de oliva virgen extra"
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Cortar el pan en rebanadas y tostar ligeramente al horno."},
            {"@type": "HowToStep", "text": "Colocar medallones de queso de cabra sobre la mitad de las tostas y añadir cebolla caramelizada."},
            {"@type": "HowToStep", "text": "Untar la otra mitad con queso crema al eneldo y coronar con láminas de salmón ahumado."},
            {"@type": "HowToStep", "text": "Decorar con brotes frescos y un hilo de aceite de oliva antes de servir."}
        ]
    }
    update_post_schema(RG_URL, RG_KEY, p5['id'], schema)
    print("Updated p5 aperitivos-deliciosos-y-faciles-para-tus-cenas-con-amigos")

# 6. Delete thin draft gambas-al-ajillo-clasicas from RecetaGenial
req = urllib.request.Request(
    f'{RG_URL}/rest/v1/posts?slug=eq.gambas-al-ajillo-clasicas',
    headers={'apikey': RG_KEY, 'Authorization': f'Bearer {RG_KEY}'},
    method='DELETE'
)
try:
    with urllib.request.urlopen(req) as r:
        print("Deleted thin draft gambas-al-ajillo-clasicas:", r.status)
except Exception as e:
    print("Delete error:", e)

# 7. RecetaDolce: pasteles-de-cumplea-os & pasteles-de-cumplea-os-bonitos
p7a = get_post(RD_URL, RD_KEY, 'pasteles-de-cumplea-os')
if p7a:
    schema = {
        "@type": "Recipe",
        "name": p7a['title'],
        "recipeYield": "10 porciones",
        "prepTime": "PT30M",
        "cookTime": "PT40M",
        "totalTime": "PT70M",
        "recipeIngredient": [
            "250 g de harina de repostería",
            "200 g de azúcar blanco",
            "4 huevos camperos",
            "100 ml de leche entera",
            "100 ml de aceite de girasol",
            "1 sobre (16 g) de levadura química en polvo",
            "1 cucharadita de extracto de vainilla",
            "300 g de nata para montar para el relleno",
            "Fresas frescas o chocolate para decorar"
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Precalentar el horno a 180°C y engrasar un molde redondo de 20-22 cm."},
            {"@type": "HowToStep", "text": "Batir los huevos con el azúcar durante 5 minutos hasta que blanqueen y doblen su volumen."},
            {"@type": "HowToStep", "text": "Añadir el aceite, la leche y la vainilla batiendo a velocidad baja."},
            {"@type": "HowToStep", "text": "Tamizar la harina con la levadura e incorporar con movimientos envolventes."},
            {"@type": "HowToStep", "text": "Verter en el molde y hornear durante 35-40 minutos hasta que al pinchar con un palillo salga limpio."},
            {"@type": "HowToStep", "text": "Dejar enfriar, cortar en capas, rellenar con la nata montada y decorar festivamente al gusto."}
        ]
    }
    update_post_schema(RD_URL, RD_KEY, p7a['id'], schema)
    print("Updated RecetaDolce pasteles-de-cumplea-os")

p7b = get_post(RD_URL, RD_KEY, 'pasteles-de-cumplea-os-bonitos')
if p7b:
    schema = {
        "@type": "Recipe",
        "name": p7b['title'],
        "recipeYield": "12 porciones",
        "prepTime": "PT45M",
        "cookTime": "PT35M",
        "totalTime": "PT80M",
        "recipeIngredient": [
            "300 g de harina de trigo",
            "250 g de azúcar",
            "4 huevos grandes",
            "150 g de mantequilla a temperatura ambiente",
            "120 ml de leche",
            "1 cucharadita de levadura química",
            "400 g de crema de mantequilla (buttercream) para cobertura",
            "Colorantes alimentarios y sprinkles para decoración"
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Precalentar el horno a 175°C y preparar moldes para capas de bizcocho."},
            {"@type": "HowToStep", "text": "Batir la mantequilla con el azúcar hasta obtener una crema suave y esponjosa."},
            {"@type": "HowToStep", "text": "Añadir los huevos uno a uno, integrando bien tras cada adición."},
            {"@type": "HowToStep", "text": "Alternar la harina tamizada con la leche hasta lograr una masa homogénea."},
            {"@type": "HowToStep", "text": "Hornear las capas durante 30-35 minutos y dejar enfriar completamente en rejilla."},
            {"@type": "HowToStep", "text": "Nivelar los bizcochos, aplicar una capa atrapamigas de crema y refrigerar 20 minutos."},
            {"@type": "HowToStep", "text": "Cubrir con la capa final de buttercream alisando con espátula y añadir decoraciones temáticas."}
        ]
    }
    update_post_schema(RD_URL, RD_KEY, p7b['id'], schema)
    print("Updated RecetaDolce pasteles-de-cumplea-os-bonitos")

# Also delete the two draft stubs in RecetaDolce
for slug in ['aperitivos-frios-faciles', 'comida-sencilla-recetas-rapidas']:
    req = urllib.request.Request(
        f'{RD_URL}/rest/v1/posts?slug=eq.{slug}',
        headers={'apikey': RD_KEY, 'Authorization': f'Bearer {RD_KEY}'},
        method='DELETE'
    )
    try:
        with urllib.request.urlopen(req) as r:
            print(f"Deleted draft {slug}:", r.status)
    except Exception as e:
        print("Delete error:", e)
