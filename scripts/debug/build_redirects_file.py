import json
import sys
sys.path.insert(0, '.')
from scripts.debug.generate_redirect_rules import redirects_map

additional = {
    '/\\$': '/search',
    '/&': '/search',
    '/quitar-verrugas-de-forma-natural': '/about',
    '/quitar-verrugas-de-forma-natural/': '/about',
    '/test-slug-123456': '/search',
    '/bizcocho-en-taza-mug-cake-de-zanahoria-test': '/categoria/postres',
    '/test-milanesa-genial': '/categoria/carnes',
    '/helado-de-fresas-con-crema-la-receta-definitiva-y-cremosa': '/categoria/postres',
    '/pipeline-integration-test-tarta-de-limon-rapida-20260424134100': '/search',
    '/pipeline-integration-test-tarta-de-limon-rapida-20260425105719': '/search',
}
redirects_map.update(additional)

lines = [
    "export interface RedirectRule {",
    "  source: string;",
    "  destination: string;",
    "  permanent: boolean;",
    "}",
    "",
    "export const RECIPE_REDIRECTS: RedirectRule[] = [",
]

for src, dst in sorted(redirects_map.items()):
    lines.append(f"  {{ source: {json.dumps(src)}, destination: {json.dumps(dst)}, permanent: true }},")

lines.append("];")
lines.append("")

out_path = r"c:\Users\REDX420\Desktop\recetagenial\lib\redirects.ts"
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Successfully wrote {len(redirects_map)} redirects to {out_path}")
