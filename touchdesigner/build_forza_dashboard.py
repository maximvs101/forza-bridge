"""Constructeur du tableau de bord de base (jauges) pour le composant Forza Bridge.

Pre-requis : le composant 'forza_bridge' existe deja (voir
build_forza_bridge_component.py) avec sa sortie CHOP 'null1' active.

A executer UNE FOIS depuis un Text DAT (langage Python) place A L'INTERIEUR
du composant forza_bridge (entrer dedans avec un double-clic avant de
creer le Text DAT, sinon les references relatives a 'null1' seront fausses).

Cree, a cote de oscin1/null1 :
  - speed_bar / speed_text : jauge + lecture numerique de la vitesse (km/h)
  - rpm_bar / rpm_text     : jauge + lecture numerique du regime moteur
  - gear_text              : rapport engage (valeur brute renvoyee par le jeu)
  - gforce_view            : point mobile dans un cadre, position = G
                              longitudinal / lateral (acceleration_z / _x)

Chaque sortie est un TOP independant : ce n'est qu'un point de depart a
habiller/assembler ensuite dans le reseau TouchDesigner de l'utilisateur.
"""

comp = parent()  # doit etre forza_bridge
CHOP = "null1"

SPEED_MAX_KMH = 300  # echelle de la jauge vitesse, a ajuster selon la voiture
GFORCE_REF = 20  # m/s^2 pris comme reference pour le cadre G (~2G)


def set_fraction_units(target_op, *par_names):
    """Bascule les parametres d'unite (size/center/radius) sur 'Fraction'."""
    for name in par_names:
        try:
            getattr(target_op.par, name).val = 'fraction'
        except Exception:
            print(
                f"Attention: impossible de regler {target_op.name}.{name} sur "
                f"'Fraction' automatiquement - a verifier manuellement dans les "
                f"parametres du TOP."
            )


def frac_expr(numerator: str, denominator) -> str:
    return f"min(1, max(0, ({numerator}) / ({denominator})))"


def make_bar(name, frac_expression, color, x):
    bar = comp.create(rectangleTOP, name)
    bar.nodeX, bar.nodeY = x, 300
    set_fraction_units(bar, 'sizeunit', 'centerunit')
    bar.par.sizey = 0.6
    bar.par.sizex.expr = frac_expression
    bar.par.centerx.expr = f"({frac_expression}) / 2 - 0.5"
    bar.par.centery = 0
    bar.par.fillcolorr, bar.par.fillcolorg, bar.par.fillcolorb = color
    bar.par.bgcolorr, bar.par.bgcolorg, bar.par.bgcolorb = (0.08, 0.08, 0.08)
    bar.par.bgalpha = 1
    return bar


def make_text(name, expr, x, y, size=48):
    t = comp.create(textTOP, name)
    t.nodeX, t.nodeY = x, y
    t.par.text.expr = expr
    t.par.fontsizex = size
    t.par.fontsizey = size
    t.par.fontcolorr, t.par.fontcolorg, t.par.fontcolorb = (1, 1, 1)
    return t


speed_frac = frac_expr(f"op('{CHOP}')['speed'][0] * 3.6", SPEED_MAX_KMH)
make_bar('speed_bar', speed_frac, (0.2, 0.6, 1.0), 300)
make_text('speed_text', f"f\"{{op('{CHOP}')['speed'][0]*3.6:.0f}} km/h\"", 300, 420)

rpm_frac = frac_expr(f"op('{CHOP}')['current_engine_rpm'][0]", f"op('{CHOP}')['engine_max_rpm'][0]")
make_bar('rpm_bar', rpm_frac, (1.0, 0.4, 0.1), 500)
make_text('rpm_text', f"f\"{{op('{CHOP}')['current_engine_rpm'][0]:.0f}} tr/min\"", 500, 420)

make_text('gear_text', f"f\"Rapport: {{int(op('{CHOP}')['gear'][0])}}\"", 700, 300, size=36)

# -- G-meter : cadre fixe + point mobile, composites ensemble --
gforce_track = comp.create(rectangleTOP, 'gforce_track')
gforce_track.nodeX, gforce_track.nodeY = 300, 550
set_fraction_units(gforce_track, 'sizeunit', 'centerunit')
gforce_track.par.sizex = 0.8
gforce_track.par.sizey = 0.8
gforce_track.par.fillalpha = 0
gforce_track.par.borderr, gforce_track.par.borderg, gforce_track.par.borderb = (1, 1, 1)
gforce_track.par.borderwidth = 4
gforce_track.par.bgcolorr, gforce_track.par.bgcolorg, gforce_track.par.bgcolorb = (0.05, 0.05, 0.05)
gforce_track.par.bgalpha = 1

gforce_dot = comp.create(circleTOP, 'gforce_dot')
gforce_dot.nodeX, gforce_dot.nodeY = 500, 550
set_fraction_units(gforce_dot, 'radiusunit', 'centerunit')
gforce_dot.par.radiusx = 0.04
gforce_dot.par.radiusy = 0.04
gforce_dot.par.centerx.expr = f"min(1, max(-1, op('{CHOP}')['acceleration_x'][0] / {GFORCE_REF})) * 0.35"
gforce_dot.par.centery.expr = f"min(1, max(-1, op('{CHOP}')['acceleration_z'][0] / {GFORCE_REF})) * 0.35"
gforce_dot.par.fillcolorr, gforce_dot.par.fillcolorg, gforce_dot.par.fillcolorb = (1, 0.2, 0.2)

gforce_view = comp.create(compositeTOP, 'gforce_view')
gforce_view.nodeX, gforce_view.nodeY = 700, 550
gforce_view.par.operand = 'over'
gforce_view.inputConnectors[0].connect(gforce_dot)
gforce_view.inputConnectors[1].connect(gforce_track)

print(
    "Tableau de bord cree : speed_bar/speed_text, rpm_bar/rpm_text, "
    "gear_text, gforce_view (cadre + point G)."
)
