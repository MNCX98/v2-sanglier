"""Contexte partagé par toutes les phases."""
from dataclasses import dataclass, field
from typing import Callable

from core.capture import WindowCapture
from core.config import Config
from core.vision import Template


@dataclass
class Context:
    config: Config
    capture: WindowCapture
    templates: list[Template] = field(default_factory=list)      # monstres
    ui_templates: list[Template] = field(default_factory=list)   # boutons / icônes du jeu
    log: Callable[[str], None] = print
    select_unverified: bool = False                              # la dernière sélection du sort n'a pas pu être vérifiée
    me_hint: tuple[int, int] | None = None                       # dernière position connue de mon personnage
    no_enemy_streak: int = 0                                     # tours de suite où aucun adversaire n'a été repéré
    hint_unverified: bool = False                                # la dernière position connue est une supposition (déplacement non vérifié)
    progress: int = 0                                            # compteur d'actions réussies (lancers, déplacements) : détecte un combat bloqué
    failed_moves: list = field(default_factory=list)             # cases visées sans succès pendant le tour en cours
    last_enemies: list = field(default_factory=list)             # dernières positions connues des adversaires (combat en cours) : repli si plus aucun n'est visible
