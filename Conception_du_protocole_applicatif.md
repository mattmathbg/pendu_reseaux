# Conception du protocole applicatif

1. Quel est le service rendu par le serveur ?
     - Le serveur permet la gestion et l'arbitrage de parties de jeu du pendu.
     - Il génère ou choisit les mots secrets, applique strictement les règles de jeu, suit la progression des essais, gère le cycle de  vie des sessions (maintien et reprise après incident) et assure la synchronisation de l'état entre les joueurs. 
     - Dans de futur extentions il permettra aussi de discuter dans un chat(global, salle ou limité entre 2 joueur), de faire du JcJ, créer des salles de jeu, Chronometre (durée maximal pour jouer), compatibilité IPv4 / IPv6, securité via TLS.

2. Quelles opérations peut demander le client ?
     - S'identifier et initier ou reprendre une session (HELLO / RESUME).   
     - Démarrer une nouvelle partie de jeu (NEW_GAME).
     - Proposer une lettre ou tenter un mot (LETTER /GUESS)
     - Consulter l'état courant de sa partie (STATE)
     - Interagir avec les salons multijoueurs (CREATE_ROOM, LIST_ROOMS, JOIN_ROOM, LEAVE_ROOM).
     - Quitter et clôturer la session proprement (QUIT)
     - D'autres opérations viendront par la suite avec les extentions mentionné dans la questions précèdentes.

3. Quelles réponses le serveur peut-il retourner ?
     - Une confirmation de session ou d'accueil (WELCOME) contenant le session_id.
     - L'état actualisé du jeu (STATE) incluant le mot masqué, le nombre d'erreurs ou d'essais restants, et l'ensemble des lettres déjà essayées.
     - La fin de partie (GAME_OVER) indiquant l'issue (victoire ou défaite) et dévoilant le mot recherché.
     - Un message d'erreur applicative standardisé (ERROR) précisant un code d'erreur textuel et une description intelligible en cas d'action invalide.   

4. Quelles informations sont conservées par le serveur pendant une partie ?
     - L'identifiant unique de session (session_id) et le pseudo du joueur.   
     - Le mot secret en clair et son état de masquage courant (ex. _ E _ _ E).   
     - La liste/ensemble des lettres déjà proposées.   
     - Le nombre d'erreurs commises et la limite d'essais autorisés.   
     - L'état courant dans la machine à états (EN_COURS, GAGNE, PERDU, SUSPENDU).   
     - L'horodatage de dernière activité pour le TTL d'expiration.   
     - Le dernier identifiant de requête (last_request_id) et sa réponse associée pour garantir l'idempotence (garantie une réponse identique a celle qui aurait du avoir lieu en cas de coupure de connexion).   


5. Qui fixe les règles du jeu : le client ou le serveur ?
     - **Uniquement** le serveur
     - Le serveur est la seule autorité : il refuse ou valide les propositions, décompte les pénalités et décrète la fin de la partie. Le client n'est qu'un afficheur et un transmetteur d'actions
6. Quelles vérifications doivent être réalisées côté serveur ?
     - Conformité syntaxique : vérifier que le message est un JSON valide et contient les champs obligatoires selon son type.
     - Validité sémantique des données : vérifier qu'une proposition est bien un caractère alphabétique unique (pas un nombre, symbole ou chaîne vide).   
     - Cohérence d'état : vérifier que l'action est licite dans l'état courant (interdire de deviner une lettre si la partie n'est pas démarrée, déjà terminée ou en pause).   
     - Détection de doublons : vérifier si la lettre a déjà été tentée auparavant dans cette session.   
     - Authenticité et droits : vérifier que le session_id existe, n'est pas expiré et appartient bien à l'interlocuteur.