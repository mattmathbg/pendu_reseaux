import json
import random
import unicodedata
import urllib.request

MOTS_SECOURS = ["PYTHON", "ASYNCHRONE", "SOCKET", "SERVEUR", "PROTOCOLE", "RESEAUX"]

def get_word_from_api(category_id: int | None = None) -> tuple[str, str]:
    """Récupère un mot aléatoire depuis l'API trouve-mot.fr."""
    try:
        url = f"https://trouve-mot.fr/api/categorie/{category_id}" if category_id else "https://trouve-mot.fr/api/random"
        response = urllib.request.urlopen(url, timeout=3.0)
        data = json.loads(response.read())
        premier_element = data[0] if isinstance(data, list) and data else {}
        mot_brut = premier_element.get("name", "")
        nom_categorie = premier_element.get("categorie", "DIVERS")
        # Retire les accents et met en majuscules
        mot_sans_accent = unicodedata.normalize('NFD', mot_brut)
        mot_propre = "".join(c for c in mot_sans_accent if unicodedata.category(c) != 'Mn').upper().strip()
        return mot_propre, nom_categorie
    except Exception as e:
        print(f"Erreur lors de la récupération du mot depuis l'API : {e}")
        return random.choice(MOTS_SECOURS), "LOCAL"