import pathlib, re

out = []
for p in pathlib.Path('.').rglob('*.py'):
    if '.venv' in str(p) or 'venv' in str(p):
        continue
    text = p.read_text(encoding='utf-8', errors='ignore')
    if 'table(' in text:
        matches = re.findall(r'\.table\(["\']([^"\']+)["\']\)', text)
        if matches:
            out.append(f"{p}: {matches}")

pathlib.Path('data/reports/tables.txt').write_text('\n'.join(out), encoding='utf-8')
print("WROTE", len(out), "FILES")
