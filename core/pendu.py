from enum import StrEnum

class GameState(StrEnum):
    """
    Représente les états possibles du cycle de vie d'une partie de pendu.
    """
    IN_PROGRESS = "in_progress"
    WON = "won"
    LOST = "lost"
    ABANDONED = "abandoned"

class PenduError(Exception):
    """Exception de base pour le jeu."""
    pass

class InvalidStateError(PenduError):
    """Action interdite dans l'état actuel de la partie."""
    pass

class InvalidLetterError(PenduError):
    """La proposition n'est pas une lettre unique valide."""
    pass

class LetterAlreadyTriedError(PenduError):
    """La lettre a déjà été proposée."""
    pass

class Pendu:
    """
    Moteur de jeu pur du Pendu (couche métier, indépendante du réseau).
    
    Responsabilités :
    - Conserver le mot secret, les lettres testées et le décompte des erreurs.
    - Valider les propositions de lettres et mettre à jour l'état de la partie.
    - Calculer l'affichage masqué du mot (ex. '_ E _ E').
    - Déterminer la victoire, la défaite ou l'abandon selon les règles fixées.
    """
    secret_word: str
    guessed_letters: set[str]
    max_errors: int
    current_errors: int
    state: GameState

    def __init__(self, secret_word: str, max_errors: int = 6) -> None:
        """
        Initialise une nouvelle instance de jeu.

        Attributs à initialiser :
        - secret_word : mot à deviner normalisé (majuscules, sans espaces superflus).
        - guessed_letters : ensemble (set) vide des lettres déjà proposées.
        - max_errors : nombre maximal d'erreurs autorisées avant la défaite.
        - current_errors : compteur d'erreurs initialisé à 0.
        - state : état initial positionné à GameState.IN_PROGRESS.
        """
        self.secret_word = secret_word.upper().strip()
        self.guessed_letters = set()
        self.max_errors = max_errors
        self.current_errors = 0
        self.state = GameState.IN_PROGRESS

    def guess(self, letter: str) -> bool:
        """
        Traite la proposition d'une lettre par le joueur.

        Règles métier :
        - Normalise la lettre reçue en majuscule.
        - Ajoute la lettre à l'ensemble `guessed_letters`.
        - Si la lettre est absente du mot secret :
            * Incrémente `current_errors`.
            * Bascule l'état à `GameState.LOST` si `current_errors >= max_errors`.
            * Retourne False.
        - Si la lettre est présente dans le mot secret :
            * Vérifie si tous les caractères alphabétiques ont été découverts.
            * Bascule l'état à `GameState.WON` si le mot est complet.
            * Retourne True.

        Exceptions levées :
        - InvalidStateError : Si la partie n'est pas en cours (`state != IN_PROGRESS`).
        - InvalidLetterError : Si l'entrée n'est pas un caractère alphabétique unique.
        - LetterAlreadyTriedError : Si la lettre a déjà été proposée.
        """
        if self.state != GameState.IN_PROGRESS:
            raise InvalidStateError("La partie n'est pas en cours.")

        letter = letter.upper()
        if len(letter) != 1 or not letter.isalpha():
            raise InvalidLetterError("Une seule lettre alphabétique est attendue.")

        if letter in self.guessed_letters:
            raise LetterAlreadyTriedError(f"La lettre '{letter}' a déjà été essayée.")

        self.guessed_letters.add(letter)

        if letter not in self.secret_word:
            self.current_errors += 1
            if self.current_errors >= self.max_errors:
                self.state = GameState.LOST
            return False  # Lettre absente (erreur comptabilisée)

        # Lettre présente : vérification de victoire
        if all(c in self.guessed_letters for c in self.secret_word if c.isalpha()):
            self.state = GameState.WON

        return True  # Bonne pioche

    def get_masked_word(self) -> str:
        """
        Génère la représentation textuelle masquée du mot secret.

        Règles d'affichage :
        - Parcourir chaque caractère du mot secret :
            * Si le caractère est dans guessed_letters : afficher la lettre.
            * Sinon : afficher un tiret bas '_'.
        - Joindre les caractères par un espace (ex. '_ E _ E') pour faciliter la lecture côté client.
        """
        res = []
        for c in self.secret_word:
            if c in self.guessed_letters or not c.isalpha():
                res.append(c)
            else:
                res.append("_")
        return " ".join(res)

    def is_finished(self) -> bool:
        """
        Indique si la partie est terminée.

        Retourne :
        - True si l'état courant est WON, LOST ou ABANDONED.
        - False si l'état est IN_PROGRESS.
        """
        pass