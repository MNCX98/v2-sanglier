# DofusAuto — corrections 0.8.9 (base 0.8.8)

Ce document conserve le contexte technique des corrections pour permettre la reprise du projet par un autre assistant ou développeur.

## Base de travail

- Archive reçue : `DofusAuto_complet.zip`.
- Version de départ : `0.8.7`.
- Journal analysé : combats 123 à 127, puis échec au transfert d'inventaire.
- Capture de référence du menu : `tests/fixtures/30_menu_transfert.png`.
- Les changements sont limités aux phases concernées ; les assets et le fonctionnement général sont conservés.

## 1. Inventaire plein — séquence d'ouverture et sens du transfert

### Séquence correcte dans Dofus Touch

1. Fermer les fenêtres déjà ouvertes.
2. Si le menu inférieur est replié, cliquer sur le triangle vert pour le déplier.
3. Cliquer sur l'icône Monture dans ce menu.
4. Dans la fenêtre de l'emplacement de la monture qui vient de s'ouvrir, détecter et cliquer sur le bouton-sac (`inv_monture_sac`). Cela ouvre l'inventaire de la monture.
5. Attendre que les titres des fenêtres « Monture » et « Inventaire » soient tous les deux détectés.
6. Cliquer uniquement sur la flèche verte pointant vers la gauche, dans la fenêtre Inventaire (à droite). Cette flèche transfère de l'inventaire du personnage vers la monture.
7. Choisir « Transférer les objets visibles » ou « Transférer tous les objets », selon la configuration.
8. Fermer les fenêtres, replier le menu si le programme l'avait lui-même déplié, puis vérifier le badge d'inventaire plein.

### Erreurs de la version précédente

La version précédente sautait l'étape 4 : après le clic sur l'icône Monture, elle cherchait directement le titre « Monture » et cliquait sur une position calculée à partir de ce titre. Or cette fenêtre de transfert n'apparaît qu'après avoir ouvert l'emplacement de la monture puis cliqué sur son bouton-sac.

Elle essayait également deux flèches successivement. Le second essai cliquait sur la flèche de la fenêtre Monture, qui pointe vers la droite et correspond au sens inverse. Pour le transfert demandé, seule la flèche de gauche de la fenêtre Inventaire doit être utilisée.

### Correction appliquée

- Le dépliage du menu inférieur avec `inv_triangle` est conservé. Si l'icône Monture n'est pas détectée, le programme clique sur le triangle vert, puis recherche à nouveau l'icône.
- Après le clic sur `inv_monture`, le programme attend maintenant le bouton-sac `inv_monture_sac` et clique dessus. Il n'utilise plus le titre « Monture » comme raccourci pour sauter cette étape.
- Après le clic sur le bouton-sac, il attend les deux titres de fenêtres.
- Il clique exclusivement sur la flèche ◀ de la fenêtre Inventaire, avec le décalage `INV_ARROW_FROM_TITLE`. Le recours à la flèche ▶ de la fenêtre Monture a été supprimé.
- Le choix du transfert, la fermeture des fenêtres, la remise en place du menu et le contrôle du badge sont conservés.
- En cas d'échec de détection du bouton-sac ou des fenêtres, une capture est enregistrée dans `logs/`.

### Limites de validation

La capture `tests/fixtures/30_menu_transfert.png` montre les deux fenêtres déjà ouvertes et le menu de transfert. Elle permet de confirmer visuellement le sens des flèches : la flèche de la fenêtre Inventaire pointe vers la gauche. En revanche, l'archive ne contient pas de capture dédiée de l'étape intermédiaire « fenêtre de l'emplacement de la monture avec bouton-sac ». Le gabarit `assets/ui/inv_monture_sac.png` est présent, mais sa détection dans cette étape doit encore être validée sur une capture réelle.

La compilation Python de `phases/p_inventaire.py` réussit. Le script global `tests/test_vision.py` n'a pas terminé dans le délai de 120 secondes ; aucun test de la séquence de clics en jeu n'a donc été validé. Un essai réel dans Dofus Touch reste indispensable.

## 2. Désélection de Coagulation avant déplacement

### Problème observé

Le journal montre plusieurs cas où le programme signale que Coagulation reste sélectionnée, ou ne retrouve plus son icône au moment de la désélection. Le déplacement est alors abandonné, car le jeu ne permet pas de déplacer le personnage tant qu'un sort est sélectionné.

Dans `phases/p4_tour.py`, `_deselect_spell()` dépendait de la détection instantanée de `sort_attaque`. Or le sort peut rester visuellement sélectionné (zone de portée visible) alors que le gabarit de son icône ne passe pas le seuil de reconnaissance sur cette capture.

### Solution appliquée

- Ajout de `attack_icon_hint` dans `phases/base.py` pour mémoriser le dernier rectangle reconnu de l'icône Coagulation.
- `_select_spell()` et `_deselect_spell()` actualisent ce repère dès que l'icône est détectée.
- Si l'icône est absente mais que le sort semble encore sélectionné, `_deselect_spell()` clique à la dernière position connue, puis vérifie que la sélection a disparu.
- Si aucune position antérieure n'existe, le programme refuse toujours de cliquer à l'aveugle et conserve un message d'erreur explicite.

### Résultat attendu

Une disparition momentanée du gabarit n'empêche plus nécessairement la désélection. Le clic de secours n'est autorisé que si une position d'icône a été réellement détectée auparavant.

### Limite

Le repère est une position mémorisée dans l'image normalisée. Si l'interface du jeu déplace la barre de sorts pendant un combat, le clic de secours peut ne plus être valide. Il faudra alors ajouter une détection spécifique de la barre plutôt que conserver le repère.

## 3. Détection de la position du personnage et confirmation des déplacements

### Méthodes de localisation déjà présentes

Le projet disposait déjà de trois indices distincts ; ils ne doivent pas être confondus :

1. **Anneau rouge entier** : `find_me()` regroupe les pixels rouges et filtre les formes selon la taille et la géométrie attendues.
2. **Anneau rouge partiellement masqué** : si l'anneau complet n'est pas trouvé, `_find_me_partial()` recherche une ellipse incomplète à partir de sa forme connue et, si possible, de la dernière position connue.
3. **Zone violette de Coagulation** : `range_mask()` repère la portée affichée quand le sort est sélectionné. `_range_center()` estime le centre de cette zone et le recale sur la grille. `my_position()` s'en sert comme solution de secours ou pour comparer la dernière position connue.

Les **cases vertes** ont un rôle différent : elles indiquent les destinations accessibles après désélection du sort. Elles ne sont pas un quatrième détecteur direct de l'anneau. La version 0.8.9 exploite toutefois leur répartition pour obtenir un indice secondaire sur le centre de la zone de déplacement.

### Problème de la version 0.8.8

Après un double-clic, `_wait_moved()` ne vérifiait que l'anneau rouge. Une détection isolée n'était pas suffisante, mais le résultat `unknown` entraînait ensuite l'essai d'une autre case. Si le premier déplacement avait réellement réussi alors que l'anneau était masqué, le programme risquait donc de cliquer une seconde destination et de déplacer le personnage une nouvelle fois.

### Modifications de la version 0.8.9

- `_wait_moved()` conserve la priorité à l'anneau rouge entier ou partiel, avec deux observations cohérentes de la nouvelle position.
- Avant le clic, si les cases vertes sont disponibles, `_green_zone_center()` estime leur centre en coordonnées de grille. Cette estimation n'est retenue que si elle est suffisamment proche de la position de départ connue.
- Après le clic, le centre vert doit être retrouvé sur deux captures, avoir quitté la position de départ et correspondre à la case visée. Il peut alors confirmer le déplacement même si l'anneau rouge n'est pas reconnu.
- Si une seule observation rouge ou verte est disponible, le résultat reste incertain.
- **En cas de résultat incertain, aucune autre case n'est cliquée pendant ce tour.** `move_uncertain` bloque aussi les tentatives de déplacement répétées dans la boucle du tour. Le programme préfère suspendre le déplacement plutôt que risquer un deuxième mouvement depuis une position inconnue.
- Si deux observations montrent que le personnage est toujours sur sa case de départ, la destination peut être considérée comme réellement ratée et une autre candidate peut être essayée.
- Le repère violet de Coagulation reste disponible dans `my_position()` comme auparavant. Il sert à estimer ou recouper la position quand l'anneau rouge manque, mais il n'est pas présenté comme une preuve directe du déplacement après le clic.

### Limites et validation nécessaire

- Les fixtures `09_mon_tour.png` et `18_nouvelle_carte_debut_tour.png` montrent des zones vertes dont le centre estimé est à environ une case de l'anneau détecté. C'est pourquoi le centre vert n'est utilisé qu'en recoupement avec la position de départ et la case cliquée.
- Les fixtures de Coagulation confirment que la zone violette peut fournir un repère, mais son centroïde est moins précis dans certaines situations, notamment sur la capture en mode créature. La dernière position connue reste donc prioritaire tant que l'écart n'est pas suffisamment important.
- Le dépôt ne contient pas de séquence vidéo ou de paire de captures avant/après un déplacement réel avec l'anneau masqué. Le secours par les cases vertes est donc testé par tests unitaires et vérifications sur les captures fixes, mais doit encore être validé en combat réel.
- Si la position reste incertaine, le programme suspend les déplacements pour le tour ; il ne garantit pas qu'il pourra attaquer ensuite depuis cette position.

## 4. Fin du combat / fin du tour

### Problème observé

Sur certains derniers tours, le journal affiche « Aucun adversaire visible », puis une tentative de désélection, puis « Bouton Fin du tour vert introuvable », avant que la fenêtre de résultat soit reconnue juste après. Cela correspond à une transition d'interface : l'animation de fin de combat peut précéder l'apparition du titre de résultat.

### Solution appliquée

- Dans `end_turn()`, si le bouton vert n'est pas visible, le programme attend maintenant jusqu'à 1,8 seconde en relisant l'interface.
- Si le titre de résultat apparaît pendant cette fenêtre, le combat est considéré terminé et aucun clic sur Fin du tour n'est tenté.
- Si le bouton Fin du tour redevient vert, le programme reprend la fin du tour normalement.
- Si aucun des deux états n'apparaît, un avertissement explicite est conservé.
- L'origine de capture est actualisée à chaque nouvelle image afin que le clic utilise les coordonnées de la capture où le bouton a été reconnu.

### Résultat attendu

Moins de faux avertissements lorsque le dernier monstre vient d'être éliminé et que la fenêtre de résultat est en cours d'apparition.

## Vérifications effectuées pour la version 0.8.9

- `py_compile` : tous les fichiers Python du projet compilent sans erreur.
- `pytest -q tests/test_movement.py` : 5 tests ciblés réussis (centre des cases vertes, confirmation rouge sur deux observations, refus d'une détection rouge isolée, confirmation verte stable, absence de clic sur une seconde case lorsque le résultat est incertain).
- Les deux images de test `31_perso_cache.png` sont reconnues aux coordonnées attendues par `find_me()`.
- Sur les captures `09_mon_tour.png` et `18_nouvelle_carte_debut_tour.png`, le centre vert estimé est respectivement à environ 1,09 et 1,00 case de l'anneau rouge détecté.
- Sur les captures de portée, le repère violet est correctement proche de l'anneau en mode normal ; il est moins précis sur la capture en mode créature et reste donc un indice secondaire.
- `tests/test_vision.py` est un script autonome et non une suite pytest. Son exécution complète n'a pas terminé dans le délai de 120 secondes lors de cette vérification ; aucun résultat global n'est revendiqué.
- Aucun déplacement ni transfert réel en jeu n'a été effectué depuis cet environnement.


## Fichiers modifiés dans la version 0.8.9

- `phases/base.py` : état `move_uncertain`.
- `phases/p4_tour.py` : estimation verte, confirmation du déplacement, arrêt prudent en cas d'incertitude et réutilisation du repère de portée.
- `tests/test_movement.py` : tests unitaires ciblés.
- `gui/app.py` : version `0.8.9`.
- `README.md` et `LISEZMOI.txt` : documentation mise à jour.

Les corrections de l'inventaire monture et de fin de combat de la version 0.8.8 sont conservées, notamment dans `phases/p_inventaire.py`.

## Reprise du projet

1. Tester d'abord le transfert d'inventaire en jeu et conserver le journal ainsi que `logs/transfert_echec_*.png` en cas d'échec.
2. Tester un combat avec plusieurs déplacements, notamment lorsque le personnage est partiellement masqué.
3. Vérifier que Coagulation est bien désélectionnée avant chaque déplacement.
4. Vérifier la fin d'un combat lorsque le dernier monstre meurt pendant la dernière action du tour.
5. Ne pas augmenter les seuils de reconnaissance au hasard : comparer les captures de diagnostic avec les gabarits concernés avant toute modification.

La version 0.8.9 est une correction de code à valider en conditions réelles ; elle ne constitue pas une garantie que toutes les variantes d'interface de Dofus Touch sont reconnues.

# Complément 0.8.10 — calibration de la confirmation par cases vertes

## Pourquoi cette correction

Les captures `09_mon_tour.png` et `18_nouvelle_carte_debut_tour.png` montrent que la médiane des cases vertes accessibles n'est pas exactement la position du personnage : elle est décalée d'une case sur l'un des axes. Utiliser directement ce centre comme position réelle pouvait donc mémoriser une position erronée.

## Changement

- Avant le clic de déplacement, le programme compare le centre de la zone verte à la position de départ connue et mesure le décalage en coordonnées de grille.
- Après le clic, il applique ce même décalage aux centres verts observés pour estimer la position du personnage.
- La confirmation verte reste secondaire : elle exige deux observations cohérentes, une position différente du départ et une correspondance avec la case visée.
- Si le décalage initial n'a pas pu être mesuré de façon fiable (pas de zone verte cohérente avant le clic), la zone verte ne confirme pas le déplacement. Le programme attend une détection rouge ou signale une incertitude ; il ne clique pas une autre case.

## Autre correction de sécurité

Si le menu inférieur a été déplié par le programme mais que l'icône Monture reste introuvable, le programme replie désormais le menu avant de quitter la procédure. Cela évite de laisser l'interface dans un état différent de celui du départ.

## Tests de la 0.8.10

- `pytest -q tests/test_movement.py` : 7 tests réussis, dont la compensation d'un décalage d'une case du centre vert et le refus d'utiliser les cases vertes sans calibration préalable.
- Les captures fixes confirment que le centre vert est décalé d'une case par rapport à l'anneau rouge sur `09_mon_tour.png` et `18_nouvelle_carte_debut_tour.png` ; ce biais est donc réel sur ces deux exemples.
- Le test global `tests/test_vision.py` s'arrête pendant son bloc de test des images de monstres (section 3j), avant les contrôles finaux. Les contrôles qui précèdent ce bloc affichent des résultats OK, mais le test global n'est pas déclaré réussi.
- Compilation syntaxique et archive vérifiées séparément.
- Aucun clic, déplacement ou transfert n'a été exécuté dans une session Dofus Touch réelle. Le secours par cases vertes et l'étape intermédiaire du bouton-sac restent à valider en jeu.

## Optimisation de la sélection des candidats de reconnaissance

`core/vision.py`, fonction `_peaks()` : le tri complet de tous les pixels au-dessus du seuil pouvait devenir coûteux sur des images bruitées. Le code sélectionne désormais les 2000 meilleurs candidats avec `numpy.argpartition`, puis trie uniquement ce sous-ensemble. Les seuils, scores et critères de séparation des détections restent inchangés.

Cette optimisation n'a pas suffi à faire terminer `tests/test_vision.py` dans l'environnement de vérification : l'exécution s'arrête toujours après le contrôle de la nouvelle carte, au début du bloc 3j consacré aux modèles de monstres. Aucun résultat de réussite globale n'est revendiqué.
