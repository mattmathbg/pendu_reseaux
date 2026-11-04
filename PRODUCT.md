# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

## Users
Étudiants, enseignants et développeurs en Réseaux M1 souhaitant jouer au jeu du Pendu ou tester/démontrer le protocole applicatif client-serveur TCP, l'idempotence et la résilience aux coupures.

## Product Purpose
Fournir une interface graphique Tkinter moderne, fluide et réactive pour le jeu du Pendu en réseau, permettant d'interagir intuitivement avec le serveur tout en inspectant et comprenant le fonctionnement du protocole applicatif TCP.

## Positioning
Client de jeu du Pendu réseau alliant ergonomie soignée (thème 'Deep Slate / Cyber Minimal') et transparence didactique (suivi des trames JSON, framing, gestion des déconnexions et reprise de session sans perte d'état).

## Operating Context
Application de bureau Python 3 avec Tkinter standard, sans dépendance tierce pour l'affichage. Fonctionne en local ou avec des serveurs distants/Docker via TCP (IPv4/IPv6).

## Capabilities and Constraints
- Barre de configuration dynamique (IP, Port, Pseudo, Connecter/Déconnecter, statut visuel coloré).
- Zone de jeu verticale épurée : dessin Canvas vectoriel fluide de la potence et du pendu, mot masqué grand format, statistiques (essais restants, erreurs, chronomètre).
- Clavier virtuel A-Z interactif avec gestion des états (actif, lettre trouvée, lettre erronée, désactivé) et saisie clavier physique.
- Inspecteur réseau rétractable (collapsible) avec coloration syntaxique des trames et événements.
- Architecture asynchrone/multithread avec queue d'événements pour garantir qu'aucune opération réseau ne fige l'interface graphique Tkinter.

## Product Principles
1. Zéro gel d'interface : séparation stricte entre I/O réseau et boucle d'affichage Tkinter.
2. Esthétique 'Deep Slate / Cyber Minimal' : contraste élevé, fonds sombres élégants (#1A1D24, #242832), accents lumineux menthe (#00E676) et corail (#FF5252).
3. Espace centré et aéré : potence et mot en haut, clavier virtuel généreux au centre, console rétractable en bas.
4. Feedback immédiat : états de boutons, animations ou transitions d'état claires, messages d'information intégrés.
