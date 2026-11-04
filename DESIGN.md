# Design System — Pendu Réseau GUI

<!-- impeccable:design-schema 1 -->

## Visual World: Deep Slate / Cyber Minimal

Un univers graphique moderne, épuré et contrasté inspiré des interfaces de jeu contemporaines et des outils développeurs haut de gamme. Le design repose sur un fond sombre profond, des surfaces superposées à faible luminosité, une typographie hiérarchisée et des accents colorés percutants (menthe néon et corail vif).

### Palette de Couleurs

| Rôle | Token / Valeur Hex | Utilisation |
|---|---|---|
| Background Base | `#12151B` | Fond principal de l'application |
| Card / Container | `#1B202A` | Surfaces des conteneurs, bandeaux et cartes |
| Elevated Surface | `#242B38` | Boutons au repos, champs de saisie, zones actives |
| Border / Separator | `#2D3444` | Délimitations subtiles (1px) |
| Border Focused | `#38BDF8` | Contour actif des champs de saisie |
| Text Primary | `#F0F3F8` | Titres, mot masqué, texte principal |
| Text Secondary | `#8F9BAE` | Sous-titres, étiquettes, statistiques |
| Text Muted | `#5A6578` | Éléments désactivés, placeholders |
| Accent Success | `#00E676` | Lettre trouvée, état connecté, manche gagnée |
| Accent Success BG | `#133829` | Fond des lettres victorieuses au clavier |
| Accent Danger | `#FF5252` | Lettre erronée, état déconnecté, potence, défaite |
| Accent Danger BG | `#3D1B22` | Fond des touches de lettres ratées |
| Accent Info / Link | `#38BDF8` | Identifiant de session, jetons, boutons d'action |
| Accent Warning | `#FFB74D` | Coupure simulée, avertissements réseau |

### Typographie

- **Mot masqué** : `Consolas` (ou `Courier New`), 32pt, Bold. Lettres avec espacement marqué (`L E T T R E`).
- **Titres & En-têtes** : `Segoe UI` (ou `Helvetica Neue`, sans-serif), 12-14pt, Bold.
- **Corps de texte / Boutons** : `Segoe UI`, 10-11pt, Semibold/Regular.
- **Inspecteur réseau / Logs** : `Consolas`, 9pt, Regular avec coloration sémantique par tag.

### Composants & Affordances

1. **Barre de Contrôle Supérieure** :
   - Formulaire compact : IP, Port, Pseudo.
   - Bouton de connexion avec indicateur LED dynamique (vert = connecté, rouge = déconnecté, orange = reconnexion/fermé).
   - Boutons de session : Nouvelle Manche, Abandonner, Simuler coupure.

2. **Zone de Jeu Verticale Épurée** :
   - **Potence Canvas** : Lignes lisses anti-crénelées (`capstyle="round"`, `joinstyle="round"`), palette sobre `#384252` pour la structure en bois/métal, corde `#FFB74D`, et corps du pendu stylisé en accent danger `#FF5252`.
   - **Affichage du Mot** : Grand lettrage lisible au centre.
   - **Pillules de Stats** : Affichage clair du temps écoulé, des erreurs actuelles et du nombre d'essais restants sous forme de badges modernes.
   - **Clavier Virtuel A-Z** : Grille ergonomique 3 rangées. Les touches changent d'état instantanément au clic (désactivation + colorisation verte si la lettre est dans le mot, rouge sombre si erronée). Raccourcis physiques du clavier reliés au clavier virtuel.

3. **Inspecteur Réseau Rétractable (Collapsible)** :
   - Entête avec bouton pliant/dépliant (`[▼ Logs réseau]` / `[▲ Masquer]`).
   - Console terminal intégrée avec coloration par type de trame (`ENVOI`, `REÇU`, `CONNEXION`, `RECONNEXION`, `ERREUR`, `INFO`).

### Robustesse Asynchrone

- L'interface ne bloque jamais le thread principal Tkinter.
- Les actions réseau (`connect`, `new_game`, `guess`, `resume`, `quit`) sont exécutées de manière asynchrone dans un thread d'arrière-plan ou via des tâches non bloquantes, avec remontée des réponses et logs via une `queue.Queue` consommée par `root.after()`.
