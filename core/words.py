import json
import random
import unicodedata
import urllib.request

MOTS_SECOURS = ["PYTHON", "ASYNCHRONE", "SOCKET", "SERVEUR", "PROTOCOLE", "RESEAUX"]

CATEGORIES: dict[int, str] = {
    0: "Toutes (Aléatoire)",
    1: "École & Instruction",
    2: "Paysages & Climat",
    3: "Qualités & Défauts",
    4: "Calcul & Mesures",
    5: "Aliments & Repas",
    6: "Corps Humain",
    7: "Sens & Intelligence",
    8: "Intérieur & Mobilier",
    9: "Industrie & Travail",
    10: "Arts",
    11: "Agriculture",
    12: "Forêt & Nature",
    13: "Gestes & Mouvements",
    14: "Époques & Saisons",
    15: "Vêtements & Toilette",
    16: "Sports & Jeux",
    17: "Bâtiment & Architecture",
    18: "Voyages",
    19: "Animaux",
    20: "Ville & Univers",
    21: "Minéraux & Végétaux",
    22: "Commerce",
    23: "Communication",
    24: "Joies & Peines",
    25: "Justice & Gouvernement",
    26: "Armée",
    27: "Santé & Hygiène",
}

def get_word_from_api(category_id: int | None = None) -> tuple[str, str]:
    """Récupère un mot aléatoire depuis l'API trouve-mot.fr."""
    try:
        if category_id and isinstance(category_id, int) and not isinstance(category_id, bool) and category_id > 0:
            url = f"https://trouve-mot.fr/api/categorie/{category_id}"
        else:
            url = "https://trouve-mot.fr/api/random"
        response = urllib.request.urlopen(url, timeout=3.0)
        data = json.loads(response.read())
        premier_element = data[0] if isinstance(data, list) and data else {}
        if not isinstance(premier_element, dict):
            raise ValueError("Réponse API inattendue.")
        mot_brut = premier_element.get("name", "")
        if not isinstance(mot_brut, str):
            raise ValueError("Champ 'name' invalide dans la réponse API.")
        nom_categorie = premier_element.get("categorie")
        if not isinstance(nom_categorie, str) or not nom_categorie.strip():
            nom_categorie = CATEGORIES.get(category_id or 0, "DIVERS")
        # Décompose les ligatures puis retire les accents et met en majuscules
        mot_decomp = mot_brut.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
        mot_sans_accent = unicodedata.normalize("NFD", mot_decomp)
        mot_propre = "".join(c for c in mot_sans_accent if unicodedata.category(c) != "Mn").upper().strip()
        if not mot_propre or not any("A" <= c <= "Z" for c in mot_propre):
            raise ValueError(f"Mot invalide reçu de l'API : {mot_brut!r}")
        return mot_propre, nom_categorie
    except Exception as e:
        print(f"Erreur lors de la récupération du mot depuis l'API : {e}")
        fallback_theme = CATEGORIES.get(category_id or 0, "DIVERS")
        return random.choice(MOTS_SECOURS), fallback_theme