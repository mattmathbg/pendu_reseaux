from enum import StrEnum
from xmlrpc.client import Boolean

class GameState(StrEnum):
    """
    Représente les états possibles du cycle de vie d'une partie de pendu.
    """
    IN_PROGRESS = "in_progress"
    WON = "won"
    LOST = "lost"
    ABANDONED = "abandoned"

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
        pass

    def guess(self, letter: str) -> Boolean:
        """
        Traite la proposition d'une lettre par le joueur.

        Règles métier :
        - Refuser si la partie n'est pas en cours (state != IN_PROGRESS).
        - Normaliser la lettre (majuscule, caractère unique alphabétique).
        - Refuser ou ignorer si la lettre a déjà été tentée (présente dans guessed_letters).
        - Ajouter la lettre à l'ensemble guessed_letters.
        - Si la lettre n'est pas dans secret_word :
            * Incrémenter current_errors.
            * Si current_errors >= max_errors : basculer l'état à GameState.LOST.
        - Si la lettre est dans secret_word :
            * Vérifier si toutes les lettres uniques du mot ont été découvertes.
            * Si oui : basculer l'état à GameState.WON.
        - Retourner True si la proposition a été prise en compte, False sinon.
        """
        pass
            
            

    def get_masked_word(self) -> str:
        """
        Génère la représentation textuelle masquée du mot secret.

        Règles d'affichage :
        - Parcourir chaque caractère du mot secret :
            * Si le caractère est dans guessed_letters : afficher la lettre.
            * Sinon : afficher un tiret bas '_'.
        - Joindre les caractères par un espace (ex. '_ E _ E') pour faciliter la lecture côté client.
        """
        pass

    def is_finished(self) -> Boolean:
        """
        Indique si la partie est terminée.

        Retourne :
        - True si l'état courant est WON, LOST ou ABANDONED.
        - False si l'état est IN_PROGRESS.
        """
        pass