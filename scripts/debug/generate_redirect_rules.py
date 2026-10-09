import os
import zipfile
import csv
import io
import json
from urllib.parse import urlparse, unquote

z = zipfile.ZipFile(r'c:\Users\REDX420\Downloads\recetagenial.com-Coverage-Drilldown-2026-10-09.zip')
content = z.read('Table.csv').decode('utf-8', errors='ignore')
reader = csv.reader(io.StringIO(content))
next(reader)
raw_urls = [r[0].strip() for r in reader if r]

# Specific redirect mappings
redirects_map = {
    # Category and static routes
    '/aperitivos': '/categoria/aperitivos',
    '/pollo-al-ajillo-facil': '/recetas/pollo-al-ajillo-facil',

    # Spanish recipes with canonical posts
    '/ensalada-de-pasta-fria-la-receta-facil-rapida-y-refrescante': '/ensalada-de-pasta-fria',
    '/arroz-al-horno-valenciano-tradicional-receta-autentica-y-facil': '/arroz-al-horno-valenciano',
    '/autentico-arroz-al-horno-valenciano-la-receta-tradicional': '/arroz-al-horno-valenciano',
    '/paella-de-marisco-clasica-receta-tradicional-y-trucos-para-el-socarrat': '/paella-de-marisco-con-socarrat-facil',
    '/cocido-madrileno-completo-tradicional': '/cocido-madrileno-completo-receta-tradicional',
    '/champinos-rellenos-de-sobrasada': '/champinones-rellenos-sobrasada-tapa-clasica',
    '/arroz-negro-con-sepia-y-alioli-receta-tradicional-facil': '/arroz-negro-con-sepia-y-alioli',
    '/arroz-negro-con-sepia-tradicional-receta-facil-y-espectacular': '/arroz-negro-con-sepia-y-alioli',
    '/autentico-arroz-del-senyoret-receta-tradicional-paso-a-paso': '/arroz-negro-con-sepia-y-alioli',
    '/autentico-arroz-con-costra-ilicitano-receta-tradicional-paso-a-paso': '/arroz-al-horno-valenciano',
    '/arroz-con-pollo-y-verduras-receta-facil-jugosa-y-tradicional': '/pollo-al-horno-con-arroz',
    '/tarta-de-queso-la-vina-receta-autentica': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/tarta-de-queso-la-vina-con-helado-gourmet-la-receta-de-san-sebastian': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/tarta-de-queso-la-vina-en-version-helado-el-sabor-de-san-sebastian-en-cada-cucharada': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/helado-gourmet-de-tarta-de-queso-la-vina-receta-artesana-paso-a-paso': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/helado-de-tarta-de-queso-la-vina-premium-la-receta-definitiva-paso-a-paso': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/helado-de-tarta-de-queso-la-vina-deluxe-receta-ultra-cremosa': '/tarta-de-queso-cremosa-air-fryer',
    '/tarta-de-queso-la-vi-a-receta-original-paso-a-paso': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/complete-guide-to-tarta-de-queso-la-vina-receta-original': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/complete-guide-to-tarta-de-queso-la-vina-receta-casera-facil': '/tarta-de-queso-estilo-mercadona-la-vina',
    '/tarta-de-queso-sin-horno-con-frutos-rojos-receta-facil-y-cremosa': '/tarta-queso-cremosa-sin-horno-receta-facil-saludable',
    '/tarta-de-queso-sin-horno-con-frutos-rojos-receta-facil-y-rapida': '/tarta-queso-cremosa-sin-horno-receta-facil-saludable',
    '/croquetas-jamon-iberico-melosas': '/croquetas-jamon-iberico-aperitivo',
    '/croquetas-de-jamon-tradicionales': '/croquetas-jamon-iberico-aperitivo',
    '/gambas-al-ajillo-clasicas-receta-tradicional': '/gambas-al-ajillo',
    '/gambas-al-ajillo-receta-espanola': '/gambas-al-ajillo',
    '/gambas-ajillo-tradicional-premium': '/gambas-al-ajillo',
    '/aperitivos-originales-para-fiestas': '/aperitivos-originales',
    '/canapes-panettone-foie-uva': '/canapes-originales',
    '/ensalada-campera-tradicional': '/ensalada-campera-tradicional-ensaladas-frescas',
    '/ensalada-templada-patata': '/ensalada-campera-tradicional-ensaladas-frescas',
    '/receta-de-paella-mixta-tradicional-el-secreto-del-socarrat-perfecto': '/paella-mixta-tradicional-el-secreto-del-socarrat-perfecto',
    '/gazpacho-andaluz-receta-facil': '/gazpacho-andaluz',
    '/pinchos-tortilla-patata': '/pincho-tortilla-de-patata-receta-facil',
    '/tortilla-de-patatas-tradicional-el-alma-de-las-tapas-espanolas': '/pincho-tortilla-de-patata-receta-facil',
    '/patatas-bravas-caseras': '/patatas-bravas-en-airfryer-con-alioli-negro',
    '/calamares-a-la-plancha': '/calamares-rellenos-de-setas-shiitake',
    '/conejo-al-ajillo-tradicional': '/pollo-al-horno-con-patatas',
    '/pollo-en-pepitoria-casero': '/pollo-al-horno-con-patatas',
    '/pulpo-a-la-gallega-polbo-a-feira': '/pescado-frito-crujiente-y-dorado',
    '/hummus-casero-rapido': '/hummus-de-lentejas-facil-y-cremoso',
    '/hummus-edamame-facil': '/hummus-de-lentejas-facil-y-cremoso',
    '/tartar-de-tomate-seco-y-aguacate': '/tartar-de-tomate-seco-y-aguacate-la-explosion-de-sabor-mediterraneo',
    '/sopa-de-melon-con-jamon': '/salmorejo-cordobes-cremoso-receta-tradicional',
    '/ensalada-quinoa-verano': '/ensalada-de-garbanzos-quinoa',
    '/ensalada-espinacas-fresas-nueces-pecanas-gourmet-final': '/ensalada-de-frutas-frescas-receta-perfecta-refrescarse',
    '/ensalada-de-lentejas-crujientes-y-tzatziki': '/ensalada-de-lentejas-vinagreta-mostaza-miel-saludable',
    '/risotto-de-setas-y-boletus-muy-cremoso-receta-autentica': '/risotto-de-setas-y-parmesano-receta-cremosa-y-facil',
    '/risotto-de-setas-y-boletus-receta-genial-y-extra-cremosa': '/risotto-de-setas-y-parmesano-receta-cremosa-y-facil',
    '/jamon-iberico-corte-y-presentacion': '/trucha-asalmonada-con-jamon-iberico-al-horno',
    '/tequenos-de-lomo-iberico': '/croquetas-jamon-iberico-aperitivo',

    # Postres / Desserts -> redirect to /categoria/postres
    '/helado-pistacho-siciliano': '/categoria/postres',
    '/helado-mango-chile-picante': '/categoria/postres',
    '/helado-chocolate-negro-intenso': '/categoria/postres',
    '/coulant-de-chocolate-blanco-y-matcha': '/categoria/postres',
    '/tarta-tatin-de-dulce-de-leche': '/categoria/postres',
    '/tarta-fresa-nata-clasica': '/categoria/postres',
    '/helado-fresa-casero': '/categoria/postres',
    '/helado-lavanda-miel-flores': '/categoria/postres',
    '/helado-casero-de-vainilla-sin-maquina-solo-3-ingredientes': '/categoria/postres',
    '/helado-limon-albahaca': '/categoria/postres',
    '/helado-coco-lima-kefir': '/categoria/postres',
    '/helado-cafe-espresso-cardamomo': '/categoria/postres',
    '/helado-caramelo-salado-breton': '/categoria/postres',
    '/helado-fresa-artesanal-cremoso': '/categoria/postres',
    '/helado-de-pistacho-artesanal-bronte': '/categoria/postres',
    '/helado-proteico-de-skyr-y-frutos-rojos': '/categoria/postres',
    '/fresas-con-crema-helado-supremo-real-el-postre-viral-irresistible': '/categoria/postres',
    '/receta-de-fresas-con-crema-helado-ultra-lujo-el-postre-gourmet-definitivo': '/categoria/postres',
    '/receta-de-fresas-con-crema-helado-supremo-guia-profesional-paso-a-paso': '/categoria/postres',
    '/receta-de-fresas-con-crema-helado-supremo-real-el-postre-viral-definitive': '/categoria/postres',
    '/fresas-con-crema-helado-supremo-real-mas-cremoso-y-facil': '/categoria/postres',
    '/fresas-con-crema-helado-gourmet-la-receta-definitiva-con-tecnica-profesional': '/categoria/postres',
    '/complete-guide-to-fresas-crema-helado': '/categoria/postres',
    '/fresas-con-chile-y-lima-fricy-receta': '/categoria/postres',
    '/batido-cremoso-de-fresas': '/categoria/postres',
    '/gazpacho-fresa-albahaca-gourmet': '/categoria/postres',
    '/receta-de-granizado-de-fresa-natural-y-saludable-sin-azucar': '/categoria/postres',
    '/mejores-recetas-con-fresas': '/categoria/postres',
    '/tiramisu-de-limon-y-albahaca': '/categoria/postres',
    '/flan-chia-mango-saludable-sin-horno': '/categoria/postres',
    '/flan-de-chia-y-mango-un-postre-exotico-y-saludable': '/categoria/postres',
    '/panna-cotta-de-coco-y-maracuya-fusion-gourmet': '/categoria/postres',
    '/postres-faciles-y-rapidos-sin-horno-mousse-de-limon-magica-en-10-minutos': '/categoria/postres',
    '/recetas-de-postres-sin-horno-faciles-y-cremosos': '/categoria/postres',
    '/galletas-tahini-chocolate-receta-fit': '/categoria/postres',
    '/galletas-de-mantequilla-caseras-crujientes-receta-facil-y-rapida': '/categoria/postres',
    '/brownie-aguacate-cacao-puro-saludable': '/categoria/postres',
    '/trufas-datiles-avellanas-energia-natural': '/categoria/postres',
    '/bizcocho-en-taza-mug-cake-de-zanahoria': '/categoria/postres',
    '/bizcocho-en-taza-mug-cake-de-zanahoria-v2': '/categoria/postres',
    '/arepa-dominicana-como-hacer-el-clasico-bizcocho-humedo-que-no-tiene-nada-que-ver-con-una-arepa': '/categoria/postres',
}

print(f"Total mapped redirects: {len(redirects_map)}")

# Check remaining from the 105
remaining = []
for u in raw_urls:
    p = unquote(urlparse(u).path.rstrip('/'))
    if p not in redirects_map and p + '/' not in redirects_map:
        remaining.append(p)

print(f"Remaining URLs (garbage / test / 404): {len(remaining)}")
for r in remaining:
    print("  404:", r)
