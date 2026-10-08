"""Canonical, domain-aware article category policy.

The production blogs intentionally expose small taxonomies. This module keeps
LLM wording and legacy category labels from leaking into published rows.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass


class CategoryPolicyError(ValueError):
    """Raised when an article cannot be assigned honestly and exactly."""


@dataclass(frozen=True)
class CategoryAssignment:
    category: str
    category_id: str | None = None


DOLCE_CATEGORY_IDS = {
    "fresas-y-nata": "2aa1c230-57b2-4488-861a-2d4e84a1a0ea",
    "tartas-y-pasteles": "40fdfb9e-7e0c-48a1-b421-5a92986fa3b2",
    "chocolates": "75af6eb9-24e7-4dc8-823d-c0aa73b2f878",
    "dulces-saludables": "08d07cf6-739a-4f2d-b337-9fed18eda37b",
}

_DOLCE_ALIASES = {
    "fresas y nata": "fresas-y-nata",
    "fresas nata": "fresas-y-nata",
    "frutas y cremas": "fresas-y-nata",
    "tartas y pasteles": "tartas-y-pasteles",
    "tartas": "tartas-y-pasteles",
    "pasteles": "tartas-y-pasteles",
    "postres": "tartas-y-pasteles",
    "galletas": "tartas-y-pasteles",
    "reposteria": "tartas-y-pasteles",
    "helados": "tartas-y-pasteles",
    "chocolate": "chocolates",
    "chocolates": "chocolates",
    "cacao": "chocolates",
    "dulces saludables": "dulces-saludables",
    "dulces saludables y ligeros": "dulces-saludables",
    "saludable": "dulces-saludables",
}

_GENIAL_ALIASES = {
    "aperitivo": "Aperitivos",
    "aperitivos": "Aperitivos",
    "aperitivos y tapas": "Aperitivos",
    "tapas y pinchos": "Aperitivos",
    "arroz": "Arroces",
    "arroces": "Arroces",
    "arroces y paellas": "Arroces",
    "carne": "Carnes",
    "carnes": "Carnes",
    "carnes y tradicion": "Carnes",
    "pescado": "Pescados",
    "pescados": "Pescados",
    "pescados y mariscos": "Pescados",
    "ensalada": "Ensaladas",
    "ensaladas": "Ensaladas",
    "ensaladas y saludable": "Ensaladas",
    "postre": "Postres",
    "postres": "Postres",
    "postres y reposteria": "Postres",
}

_DESSERT = re.compile(
    r"\b(tartas?|tortas?|pastel(?:es)?|bizcochos?|brownies?|galletas?|mousses?|"
    r"helados?|flan(?:es)?|natillas?|torrijas?|postres?|chocolates?|cacao|ganache|"
    r"trufas?|macarons?|eclairs?|pavlovas?|milhojas|profiteroles?|merengues?|"
    r"cupcakes?|magdalenas?|caramelos?|crema (?:brulee|catalana|dulce)|creme brulee|"
    r"arroz con leche|turron|reposteria|pasteleria|dulces?|cheesecakes?|financiers?|"
    r"coulants?|tiramisus?|panettones?|panna cotta|carlotas?|charlottes?|crepas?|"
    r"crepes?|donuts?|rosquillas?|bienmesabe|brazo de gitano|polos?|saint honore|"
    r"fresas? (?:con|y) nata|lamines)\b"
)
_SAVORY = re.compile(
    r"\b(pollos?|terneras?|carnes?|cerdos?|corderos?|ragus?|salmon|atunes?|"
    r"bacalaos?|merluzas?|pescados?|mariscos?|paellas?|croquetas?|tortillas? "
    r"(?:de )?patatas?|ensaladas?|gazpachos?|garbanzos?|lentejas?|aperitivos?|"
    r"pucheros?|sopas?|berenjenas?|calabacines? rellenos?|bocadillos?|tapas?)\b"
)
_SAVORY_PASTRY = re.compile(r"\b(pastel(?:es)?|tartas?) salados?\b")
_HEALTHY = re.compile(r"\b(saludables?|sin azucar|avena|fit|proteicos?|veganos?|ligeros?|bajo en|platano)\b")
_BERRIES = re.compile(r"\b(fresas?|frutos rojos|frambuesas?|arandanos?|moras?|cerezas?)\b")
_CHOCOLATE = re.compile(r"\b(chocolates?|cacao|brownies?|ganache|trufas?|nutella)\b")

_GENIAL_DESSERT = re.compile(
    r"\b(tartas?|pastel(?:es)?|bizcochos?|brownies?|galletas?|mousses?|helados?|"
    r"flan(?:es)?|natillas?|torrijas?|postres?|chocolates?|crema catalana|"
    r"arroz con leche|yogur con|merengues?|magdalenas?|cupcakes?|dulces?|turron|eclairs?)\b"
)
_GENIAL_SALAD = re.compile(r"\b(ensaladas?|gazpachos?|salmorejos?|pokes?|bowls?|tabule|tabbouleh)\b")
_GENIAL_RICE = re.compile(r"\b(paellas?|arroz|arroces|risottos?|fideuas?)\b")
_GENIAL_APPETIZER = re.compile(
    r"\b(aperitivos?|tapas?|canapes?|croquetas?|hummus|dips?|bravas|tostas?|"
    r"tostadas?|empanadas?|empanadillas?|bocaditos?|bocados?|bunuelos?|pinchos?|"
    r"brochetas?|guacamole|tartar|quesos?|sandwiches?|tequenos?|alcachofas?|"
    r"tortillas?|pan de ajo|papas arrugadas)\b"
)
_GENIAL_FISH = re.compile(
    r"\b(pescados?|salmon|atunes?|bonitos?|bacalaos?|merluzas?|gambas?|langostinos?|"
    r"mariscos?|mejillones?|almejas?|pulpos?|calamares?|sepias?|doradas?|lubinas?|"
    r"corvinas?|sardinas?|anchoas?|ventresca|ceviches?|tiraditos?|marmitakos?|"
    r"bogavantes?|berberechos?|caballas?)\b"
)
_GENIAL_MEAT = re.compile(
    r"\b(pollos?|terneras?|cerdos?|corderos?|carnes?|costillas?|albondigas?|"
    r"hamburguesas?|burgers?|pavos?|conejos?|carrilleras?|chorizos?|lomos?|pucheros?)\b"
)


def fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _approved(target: str, categories: Iterable[str], domain_handle: str) -> CategoryAssignment:
    allowed = tuple(categories)
    if target not in allowed:
        raise CategoryPolicyError(
            f"Category policy for {domain_handle} resolved '{target}', but the domain manifest does not allow it"
        )
    return CategoryAssignment(target, DOLCE_CATEGORY_IDS.get(target))


def _dolce_category(categories: Iterable[str], requested: object, context: str) -> CategoryAssignment:
    text = fold(context)
    if text:
        dessert = bool(_DESSERT.search(text))
        if _SAVORY_PASTRY.search(text) or (_SAVORY.search(text) and not dessert):
            raise CategoryPolicyError("Savory or off-niche content cannot be published on RecetaDolce")
        if not dessert:
            raise CategoryPolicyError("RecetaDolce article has no reliable dessert category signal")
        if _HEALTHY.search(text):
            return _approved("dulces-saludables", categories, "recetadolce")
        if _BERRIES.search(text):
            return _approved("fresas-y-nata", categories, "recetadolce")
        if _CHOCOLATE.search(text):
            return _approved("chocolates", categories, "recetadolce")
        return _approved("tartas-y-pasteles", categories, "recetadolce")

    requested_folded = fold(requested)
    target = _DOLCE_ALIASES.get(requested_folded, requested if isinstance(requested, str) else "")
    return _approved(str(target), categories, "recetadolce")


def _genial_category(categories: Iterable[str], requested: object, context: str) -> CategoryAssignment:
    text = fold(context)
    target = ""
    if text:
        if _SAVORY_PASTRY.search(text):
            target = "Aperitivos"
        elif _GENIAL_DESSERT.search(text):
            target = "Postres"
        elif _GENIAL_SALAD.search(text):
            target = "Ensaladas"
        elif _GENIAL_RICE.search(text):
            target = "Arroces"
        elif _GENIAL_APPETIZER.search(text):
            target = "Aperitivos"
        elif _GENIAL_FISH.search(text):
            target = "Pescados"
        elif _GENIAL_MEAT.search(text):
            target = "Carnes"
        else:
            raise CategoryPolicyError("RecetaGenial article has no reliable category signal")
    else:
        requested_folded = fold(requested)
        target = _GENIAL_ALIASES.get(requested_folded, requested if isinstance(requested, str) else "")
    return _approved(str(target), categories, "recetagenial")


def assign_article_category(
    *,
    domain_handle: str,
    categories: Iterable[str],
    requested: object,
    context: str = "",
) -> CategoryAssignment:
    """Return the exact public category or fail closed for production domains."""
    if domain_handle == "recetadolce":
        return _dolce_category(categories, requested, context)
    if domain_handle == "recetagenial":
        return _genial_category(categories, requested, context)

    allowed = tuple(categories)
    by_fold = {fold(category): category for category in allowed}
    target = by_fold.get(fold(requested))
    if not target:
        raise CategoryPolicyError(f"Unknown category '{requested}' for {domain_handle}")
    return CategoryAssignment(target)
