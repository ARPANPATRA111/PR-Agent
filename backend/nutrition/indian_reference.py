"""Versioned Indian household serving references used by both estimators.

Core ingredient values are aligned to ICMR-NIN IFCT 2017. Prepared-dish rows
are transparent representative household portions, not laboratory claims.
"""

from decimal import Decimal


def d(value: str) -> Decimal:
    return Decimal(value)


# Per 100 g/ml values. IFCT 2017 reports energy in kJ; kcal values here are
# converted and rounded for display. Recipe-dependent foods remain estimates.
PER_100 = {
    "paneer": {
        "calories": d("305.45"),
        "protein": d("18.86"),
        "carbohydrate": d("2.41"),
        "fat": d("24.78"),
    },
    "whole cow milk": {
        "calories": d("72.90"),
        "protein": d("3.26"),
        "carbohydrate": d("4.94"),
        "fat": d("4.48"),
    },
    "whole buffalo milk": {
        "calories": d("107.31"),
        "protein": d("3.68"),
        "carbohydrate": d("8.39"),
        "fat": d("6.58"),
    },
    "boiled egg": {
        "calories": d("147.71"),
        "protein": d("13.43"),
        "carbohydrate": d("0.75"),
        "fat": d("10.54"),
    },
    "boiled egg white": {
        "calories": d("52.58"),
        "protein": d("12.37"),
        "carbohydrate": d("0.73"),
        "fat": d("0.26"),
    },
    "boiled egg yolk": {
        "calories": d("308.32"),
        "protein": d("16.13"),
        "carbohydrate": d("3.62"),
        "fat": d("27.46"),
    },
}


# Representative home portions. Macros vary with recipe, oil, water and size;
# that uncertainty is always presented to the user as an assumption.
PER_SERVING = {
    "medium roti": {
        "aliases": ("roti", "rotis", "chapati", "chapatis"),
        "unit": "piece",
        "grams": d("40"),
        "calories": d("120"),
        "protein": d("3.5"),
        "carbohydrate": d("22"),
        "fat": d("2.5"),
    },
    "medium banana": {
        "aliases": ("banana", "bananas"),
        "unit": "piece",
        "grams": d("118"),
        "calories": d("105"),
        "protein": d("1.3"),
        "carbohydrate": d("27"),
        "fat": d("0.4"),
    },
    "boiled egg": {
        "aliases": (
            "egg",
            "eggs",
            "whole egg",
            "whole eggs",
            "boiled egg",
            "boiled eggs",
        ),
        "unit": "egg",
        "grams": d("50"),
        "calories": d("73.86"),
        "protein": d("6.715"),
        "carbohydrate": d("0.375"),
        "fat": d("5.270"),
    },
    "boiled egg white": {
        "aliases": ("egg white", "egg whites"),
        "unit": "egg white",
        "grams": d("33"),
        "calories": d("17.35"),
        "protein": d("4.082"),
        "carbohydrate": d("0.241"),
        "fat": d("0.086"),
    },
    "boiled egg yolk": {
        "aliases": ("egg yolk", "egg yolks", "yolk", "yolks"),
        "unit": "egg yolk",
        "grams": d("17"),
        "calories": d("52.41"),
        "protein": d("2.742"),
        "carbohydrate": d("0.615"),
        "fat": d("4.668"),
    },
    "plain idli": {
        "aliases": ("idli", "idlis"),
        "unit": "piece",
        "grams": d("50"),
        "calories": d("70"),
        "protein": d("2.0"),
        "carbohydrate": d("14"),
        "fat": d("0.4"),
    },
    "plain dosa": {
        "aliases": ("dosa", "dosas"),
        "unit": "piece",
        "grams": d("100"),
        "calories": d("170"),
        "protein": d("4.0"),
        "carbohydrate": d("30"),
        "fat": d("4.0"),
    },
    "cooked white rice bowl": {
        "aliases": ("rice", "white rice", "chawal"),
        "unit": "bowl",
        "grams": d("180"),
        "calories": d("235"),
        "protein": d("4.3"),
        "carbohydrate": d("51"),
        "fat": d("0.5"),
    },
    "toor dal bowl": {
        "aliases": ("toor dal", "arhar dal", "tuvar dal"),
        "unit": "bowl",
        "grams": d("150"),
        "calories": d("170"),
        "protein": d("7.0"),
        "carbohydrate": d("25"),
        "fat": d("4.5"),
    },
    "moong dal bowl": {
        "aliases": ("moong dal", "mung dal"),
        "unit": "bowl",
        "grams": d("150"),
        "calories": d("155"),
        "protein": d("7.5"),
        "carbohydrate": d("24"),
        "fat": d("3.5"),
    },
    "masoor dal bowl": {
        "aliases": ("masoor dal", "red lentil dal"),
        "unit": "bowl",
        "grams": d("150"),
        "calories": d("165"),
        "protein": d("8.5"),
        "carbohydrate": d("25"),
        "fat": d("3.5"),
    },
    "chana dal bowl": {
        "aliases": ("chana dal", "split bengal gram"),
        "unit": "bowl",
        "grams": d("150"),
        "calories": d("190"),
        "protein": d("8.0"),
        "carbohydrate": d("28"),
        "fat": d("5.0"),
    },
    "urad dal bowl": {
        "aliases": ("urad dal", "black gram dal"),
        "unit": "bowl",
        "grams": d("150"),
        "calories": d("185"),
        "protein": d("8.0"),
        "carbohydrate": d("26"),
        "fat": d("5.0"),
    },
    "rajma curry bowl": {
        "aliases": ("rajma", "kidney bean curry"),
        "unit": "bowl",
        "grams": d("180"),
        "calories": d("245"),
        "protein": d("10.0"),
        "carbohydrate": d("35"),
        "fat": d("7.0"),
    },
    "chole bowl": {
        "aliases": ("chole", "chana masala", "chickpea curry"),
        "unit": "bowl",
        "grams": d("180"),
        "calories": d("270"),
        "protein": d("10.5"),
        "carbohydrate": d("37"),
        "fat": d("9.0"),
    },
    "sambar bowl": {
        "aliases": ("sambar", "sambhar"),
        "unit": "bowl",
        "grams": d("200"),
        "calories": d("130"),
        "protein": d("6.0"),
        "carbohydrate": d("20"),
        "fat": d("3.5"),
    },
    "vegetable khichdi bowl": {
        "aliases": ("khichdi", "vegetable khichdi"),
        "unit": "bowl",
        "grams": d("250"),
        "calories": d("300"),
        "protein": d("9.0"),
        "carbohydrate": d("50"),
        "fat": d("7.0"),
    },
    "plain dahi bowl": {
        "aliases": ("dahi", "curd", "yogurt"),
        "unit": "bowl",
        "grams": d("200"),
        "calories": d("122"),
        "protein": d("7.0"),
        "carbohydrate": d("9"),
        "fat": d("6.5"),
    },
    "mixed sprouts bowl": {
        "aliases": ("sprouts", "mixed sprouts"),
        "unit": "bowl",
        "grams": d("100"),
        "calories": d("105"),
        "protein": d("7.0"),
        "carbohydrate": d("18"),
        "fat": d("1.0"),
    },
    "cooked soy chunks bowl": {
        "aliases": ("soy chunks", "soya chunks", "soyabean chunks"),
        "unit": "bowl",
        "grams": d("100"),
        "calories": d("170"),
        "protein": d("17.0"),
        "carbohydrate": d("15"),
        "fat": d("6.0"),
    },
    "poha bowl": {
        "aliases": ("poha",),
        "unit": "bowl",
        "grams": d("200"),
        "calories": d("280"),
        "protein": d("6.0"),
        "carbohydrate": d("48"),
        "fat": d("7.0"),
    },
    "upma bowl": {
        "aliases": ("upma",),
        "unit": "bowl",
        "grams": d("200"),
        "calories": d("260"),
        "protein": d("6.0"),
        "carbohydrate": d("43"),
        "fat": d("7.0"),
    },
}


LLM_REFERENCE = """Indian reference anchors (approximate): paneer 18.86 g
protein/100 g; cow milk 3.26 g/100 ml; buffalo milk 3.68 g/100 ml;
boiled whole egg 6.715 g/egg; boiled white 4.082 g/white; boiled yolk
2.742 g/yolk. Representative bowls: toor 7.0 g, moong 7.5 g, masoor
8.5 g, chana dal 8.0 g, urad dal 8.0 g, rajma 10.0 g, chole 10.5 g,
sambar 6.0 g, khichdi 9.0 g, dahi 7.0 g, sprouts 7.0 g, soy chunks
17.0 g. Ask one concise clarification for a vague generic 'dal', unspecified
paneer curry, unknown mixed dish, or missing portion where a useful estimate
cannot be made. Never silently treat egg whites, yolks and whole eggs alike."""
