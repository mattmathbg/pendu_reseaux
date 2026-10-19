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