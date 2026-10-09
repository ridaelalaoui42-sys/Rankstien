genial_redirects = [
    ("/pollo-al-horno-tiempo-temperatura-perfectos", "/pollo-al-horno-tiempo-y-temperatura-perfectos"),
    ("/salmon-horno-miel-mostaza", "/salmon-al-horno-con-miel-y-mostaza"),
    ("/tarta-de-queso-cremosa-air-fryer", "/tarta-de-queso-cremosa-en-air-fryer"),
    ("/pollo-horno-patatas-cebolla", "/pollo-al-horno-con-patatas-y-cebolla"),
    (
        "/croquetas-caseras-en-freidora-de-aire-crujientes-y-ligeras",
        "/croquetas-caseras-freidora-aire-crujientes-ligeras",
    ),
    ("/paella-mixta-marisco-pollo", "/paella-mixta-de-marisco-y-pollo"),
    ("/pescado-frito-crujiente-estilo-espanol", "/pescado-frito-crujiente-al-estilo-espanol"),
    ("/pescado-frito-crujiente-estilo-casero", "/pescado-frito-crujiente-al-estilo-casero"),
    ("/pescado-frito-crujiente-tradicional", "/pescado-frito-crujiente-al-estilo-tradicional"),
    (
        "/salmon-al-horno-verduras-receta-facil-saludable",
        "/salmon-al-horno-con-verduras-la-receta-mas-facil-y-saludable",
    ),
    (
        "/salmon-al-horno-con-verduras-receta-facil-saludable",
        "/salmon-al-horno-con-verduras-la-receta-mas-facil-y-saludable",
    ),
    ("/pollo-al-horno-con-patatas", "/pollo-horno-con-patatas"),
    ("/ensalada-de-quinoa-kale-y-aguacate", "/ensalada-quinoa-kale-aguacate"),
    ("/pollo-horno-con-papas", "/pollo-al-horno-con-papas"),
    (
        "/croquetas-caseras-jamon-iberico-freidora-aire",
        "/croquetas-caseras-de-jamon-iberico-en-freidora-de-aire",
    ),
    ("/pescado-frito-crujiente-saboroso", "/pescado-frito-crujiente-y-saboroso"),
    ("/ensalada-de-garbanzos-y-aguacate", "/ensalada-garbanzos-aguacate"),
    ("/tarta-de-queso-al-horno-cremosa", "/tarta-de-queso-al-horno-cremosa-y-facil"),
    ("/tarta-tres-chocolates-de-mercadona", "/tarta-tres-chocolates-mercadona"),
    ("/milanesa-napolitana-al-horno-jugosa-crujiente", "/milanesa-napolitana-al-horno"),
]

dolce_redirects = [
    ("/bizcocho-chocolate-para-hombre", "/bizcocho-de-chocolate-para-hombre"),
    ("/bizcocho-chocolate-dulce-leche", "/bizcocho-de-chocolate-con-dulce-de-leche"),
    ("/tarta-queso-cremosa-freidora-aire", "/tarta-de-queso-cremosa-en-freidora-de-aire"),
    ("/galletas-avena-platano-saludables", "/galletas-de-avena-y-platano-saludables"),
    ("/tarta-de-queso-freidora-aire", "/tarta-de-queso-en-freidora-de-aire"),
    ("/galletas-avena-chispas-chocolate", "/galletas-de-avena-con-chispas-de-chocolate"),
    ("/bizcocho-chocolate-blanco-esponjoso", "/bizcocho-de-chocolate-blanco-esponjoso"),
    ("/bizcocho-chocolate-esponjoso-yogur", "/bizcocho-de-chocolate-esponjoso-con-yogur"),
    ("/tarta-opera-clasica-francesa", "/tarta-opera-clasica-francesa-receta-paso-a-paso"),
    ("/macarons-de-lavanda-y-miel", "/macarons-de-lavanda-y-miel-receta-perfecta"),
]

# Update RecetaGenial
genial_file = r"c:\Users\REDX420\Desktop\recetagenial\lib\redirects.ts"
with open(genial_file, encoding="utf-8") as f:
    genial_code = f.read()

# Insert before closing ];
existing_sources = set()
for line in genial_code.split("\n"):
    if 'source: "' in line:
        src = line.split('source: "')[1].split('"')[0]
        existing_sources.add(src)

new_entries = []
for src, dst in genial_redirects:
    if src not in existing_sources:
        new_entries.append(f'  {{ source: "{src}", destination: "{dst}", permanent: true }},')

if new_entries:
    genial_code = genial_code.rstrip().rstrip("];").rstrip() + "\n" + "\n".join(new_entries) + "\n];\n"
    with open(genial_file, "w", encoding="utf-8") as f:
        f.write(genial_code)
    print(f"Added {len(new_entries)} redirects to RecetaGenial lib/redirects.ts")

# Create / Update RecetaDolce redirects
dolce_red_file = r"c:\Users\REDX420\Desktop\recetadolce\lib\redirects.ts"
dolce_content = "export interface RedirectRule {\n  source: string;\n  destination: string;\n  permanent: boolean;\n}\n\nexport const RECIPE_REDIRECTS: RedirectRule[] = [\n"
for src, dst in dolce_redirects:
    dolce_content += f'  {{ source: "{src}", destination: "{dst}", permanent: true }},\n'
dolce_content += "];\n"

with open(dolce_red_file, "w", encoding="utf-8") as f:
    f.write(dolce_content)
print(f"Created RecetaDolce lib/redirects.ts with {len(dolce_redirects)} redirects")

# Update RecetaDolce next.config.ts to import and include RECIPE_REDIRECTS
dolce_conf_file = r"c:\Users\REDX420\Desktop\recetadolce\next.config.ts"
with open(dolce_conf_file, encoding="utf-8") as f:
    conf = f.read()

if "RECIPE_REDIRECTS" not in conf:
    conf = 'import { RECIPE_REDIRECTS } from "./lib/redirects";\n' + conf
    # replace redirects()
    old_red = """  async redirects() {
    return [
      { source: '/sobre-nosotros', destination: '/about', permanent: true },
      { source: '/nuestra-historia', destination: '/about', permanent: true },
      { source: '/sobre%20nosotros', destination: '/about', permanent: true },
    ];
  },"""
    new_red = """  async redirects() {
    return [
      ...RECIPE_REDIRECTS,
      { source: '/sobre-nosotros', destination: '/about', permanent: true },
      { source: '/nuestra-historia', destination: '/about', permanent: true },
      { source: '/sobre%20nosotros', destination: '/about', permanent: true },
    ];
  },"""
    conf = conf.replace(old_red, new_red)
    with open(dolce_conf_file, "w", encoding="utf-8") as f:
        f.write(conf)
    print("Updated RecetaDolce next.config.ts with RECIPE_REDIRECTS")
