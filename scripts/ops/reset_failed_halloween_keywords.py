import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

keywords_to_reset = [
    "Cupcakes de chocolate con cerebros de crema de mantequilla",
    "Pimientos naranjas rellenos tallados como calabazas de Halloween",
    "Mini pizzas momia con queso fundido y aceitunas negras",
    "Albóndigas terroríficas con salsa de tomate sangrienta",
    "Arroz negro con calamares y ojos de huevo de codorniz",
    "Tartaletas de chocolate y ganache con lápidas de galleta",
    "Tarta de queso japonesa con sirope de frutos rojos sangriento",
    "Galletas de araña con bombón de chocolate y patas de pretzel",
    "Bizcocho de chocolate negro y glaseado naranja de Halloween"
]

for domain in ["recetadolce", "recetagenial"]:
    file_path = PROJECT_ROOT / "data" / "domains" / domain / "keywords.md"
    if not file_path.exists():
        continue
    content = file_path.read_text(encoding="utf-8")
    original = content
    for kw in keywords_to_reset:
        pattern = re.compile(r"(\|\s*" + re.escape(kw) + r"\s*\|[^|]+\|[^|]+\|[^|]+\|[^|]+\|\s*)Failed(\s*\|)", re.IGNORECASE)
        content = pattern.sub(r"\g<1>Pending\g<2>", content)
    if content != original:
        file_path.write_text(content, encoding="utf-8")
        print(f"Updated {domain} keywords.md: reset keywords to Pending")

print("Reset completed.")
