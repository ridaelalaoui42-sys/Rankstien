import json
import re


def update_redirects_file(filepath, new_redirects_map):
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Parse existing rules
    # Pattern: { source: "...", destination: "...", permanent: true }
    rule_regex = re.compile(
        r'\{\s*source:\s*"([^"]+)",\s*destination:\s*"([^"]+)",\s*permanent:\s*(true|false)\s*\}'
    )
    existing_rules = {}
    for match in rule_regex.finditer(content):
        src, dst = match.group(1), match.group(2)
        existing_rules[src] = dst

    # Add new rules
    for src, dst in new_redirects_map.items():
        existing_rules[src] = dst

    # Sort rules alphabetically by source
    sorted_sources = sorted(existing_rules.keys())

    lines = [
        "export interface RedirectRule {",
        "  source: string;",
        "  destination: string;",
        "  permanent: boolean;",
        "}",
        "",
        "export const RECIPE_REDIRECTS: RedirectRule[] = [",
    ]

    for src in sorted_sources:
        dst = existing_rules[src]
        lines.append(f'  {{ source: "{src}", destination: "{dst}", permanent: true }},')

    lines.append("];")
    lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Updated {filepath} with {len(sorted_sources)} redirect rules.")


with open("data/reports/rg_new_redirects.json", encoding="utf-8") as f:
    rg_new = json.load(f)

with open("data/reports/rd_new_redirects.json", encoding="utf-8") as f:
    rd_new = json.load(f)

update_redirects_file("c:/Users/REDX420/Desktop/recetagenial/lib/redirects.ts", rg_new)
update_redirects_file("c:/Users/REDX420/Desktop/recetadolce/lib/redirects.ts", rd_new)
