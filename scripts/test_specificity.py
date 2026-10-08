"""Test the keyword specificity gate against known good/vague keywords."""
import sys
sys.path.insert(0, ".")
from rankstein.trend_intelligence import _keyword_specificity_score

CASES = [
    # (keyword, expect_accept)
    ("tarta de manzana", True),
    ("galletas de jengibre y canela", True),
    ("pastel de zanahoria y nueces", True),
    ("tarta la viña", True),
    ("ensalada de lentejas", True),
    ("croquetas de jamón", True),
    ("salmorejo cordobés", True),
    ("arroz con leche", True),
    ("panna cotta de vainilla", True),
    ("pulpo a la gallega", True),
    ("torrijas caramelizadas", True),
    ("pasteles marroquíes", True),
    ("galletas dia del niño", True),
    ("tarta de cumpleaños mujer", True),
    # Vague — must be rejected
    ("Aperitivo irresistible en minutos", False),
    ("APERITIVO RÁPIDO Y FACIL", False),
    ("aperitivos fáciles y rápidos", False),
    ("postres ideas para vender", False),
    ("postres recetas saludables", False),
    ("pasteles recetas faciles y economicas", False),
    ("galletas recetas", False),
    ("galletas recetas faciles", False),
    ("galletas recetas caseras", False),
    ("pasteles ideas mujer", False),
    ("pasteles para hombre", False),
    ("comida tapas", False),
    ("Cursos de repostería y cocina", False),
    ("recetas de temporada", False),
    ("ideas galletas halloween", True),
    ("postres caseros", False),
    ("Recetas de Panna Cotta Casera", True),  # dish + qualifier, scrapes fine
    ("Chocolate", False),
    ("pastel", False),
]

fails = 0
for keyword, expect in CASES:
    score = _keyword_specificity_score(keyword)
    accepted = score > 0
    ok = accepted == expect
    if not ok:
        fails += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] score={score:4.1f} expect={'accept' if expect else 'reject'}: {keyword}")

print()
print(f"{len(CASES) - fails}/{len(CASES)} correct" + ("" if fails == 0 else f" — {fails} FAILURES"))
