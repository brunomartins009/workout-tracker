"""The application's fixed exercise library.

`EXERCISES` is the source of truth for which exercises exist and how they are
classified. Users cannot create, edit or delete exercises through the UI; the
library changes by editing this list and running:

    flask --app run sync-exercise-library

The sync never deletes or recreates exercises. Exercises are matched by name
(ignoring surrounding whitespace and case), so an existing row keeps its id and
every workout that references it.

`XXXXX` marks a group or subgroup that still needs a confident classification.
"""

import unicodedata

import click
from flask.cli import with_appcontext
from sqlalchemy import select

from app.database import db
from app.models import UNCLASSIFIED, Exercise


EXERCISES = [
    # Abdômen
    {"name": "Abdominal curto", "muscle_group": "Abdômen", "muscle_subgroup": "Reto abdominal"},
    {"name": "Abdominal infra", "muscle_group": "Abdômen", "muscle_subgroup": "Reto abdominal"},
    {"name": "Abdominal oblíquo", "muscle_group": "Abdômen", "muscle_subgroup": "Oblíquos"},
    {"name": "Prancha", "muscle_group": "Abdômen", "muscle_subgroup": "Reto abdominal"},
    # Braços
    {"name": "Rosca alternada com halteres", "muscle_group": "Braços", "muscle_subgroup": "Bíceps"},
    {"name": "Rosca com barra W", "muscle_group": "Braços", "muscle_subgroup": "Bíceps"},
    {"name": "Rosca concentrada", "muscle_group": "Braços", "muscle_subgroup": "Bíceps"},
    {"name": "Rosca direta com barra", "muscle_group": "Braços", "muscle_subgroup": "Bíceps"},
    {"name": "Rosca Scott com barra W", "muscle_group": "Braços", "muscle_subgroup": "Bíceps"},
    {"name": "Rosca Scott unilateral", "muscle_group": "Braços", "muscle_subgroup": "Bíceps"},
    {"name": "Tríceps com barra V", "muscle_group": "Braços", "muscle_subgroup": "Tríceps"},
    {"name": "Tríceps corda na polia", "muscle_group": "Braços", "muscle_subgroup": "Tríceps"},
    {"name": "Tríceps francês unilateral na polia", "muscle_group": "Braços", "muscle_subgroup": "Tríceps"},
    {"name": "Tríceps francês corda na polia", "muscle_group": "Braços", "muscle_subgroup": "Tríceps"},
    {"name": "Tríceps testa com barra W", "muscle_group": "Braços", "muscle_subgroup": "Tríceps"},
    {"name": "Rosca de punho com barra", "muscle_group": "Braços", "muscle_subgroup": "Antebraço"},
    # Costas
    {"name": "Barra fixa pegada pronada", "muscle_group": "Costas", "muscle_subgroup": "Latíssimo do dorso"},
    {"name": "Pulldown pegada aberta", "muscle_group": "Costas", "muscle_subgroup": "Latíssimo do dorso"},
    {"name": "Pulldown pegada fechada", "muscle_group": "Costas", "muscle_subgroup": "Latíssimo do dorso"},
    {"name": "Pullover na polia", "muscle_group": "Costas", "muscle_subgroup": "Latíssimo do dorso"},
    {"name": "Encolhimento com halteres", "muscle_group": "Costas", "muscle_subgroup": "Trapézio superior"},
    {"name": "Hiperextensão lombar", "muscle_group": "Costas", "muscle_subgroup": "Lombar"},
    # Rows work the lats and the middle of the back together; the subgroup is
    # left for a manual decision instead of guessing.
    {"name": "Remada cavalinho", "muscle_group": "Costas", "muscle_subgroup": "Latíssimo do dorso"},
    {"name": "Remada sentado pegada fechada", "muscle_group": "Costas", "muscle_subgroup": "Latíssimo do dorso"},
    {"name": "Remada unilateral sentado máquina", "muscle_group": "Costas", "muscle_subgroup": "Latíssimo do dorso"},
    # Ombros
    {"name": "Desenvolvimento com barra", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide anterior"},
    {"name": "Desenvolvimento sentado com halteres", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide anterior"},
    {"name": "Elevação frontal com halteres", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide anterior"},
    {"name": "Elevação lateral com halteres", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide lateral"},
    {"name": "Elevação lateral na polia", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide lateral"},
    {"name": "Elevação lateral sentado", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide lateral"},
    {"name": "Crucifixo invertido com halteres", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide posterior"},
    {"name": "Crucifixo invertido máquina", "muscle_group": "Ombros", "muscle_subgroup": "Deltoide posterior"},
    # Peito
    {"name": "Crucifixo inclinado com halteres", "muscle_group": "Peito", "muscle_subgroup": "Peitoral clavicular"},
    {"name": "Supino 30º", "muscle_group": "Peito", "muscle_subgroup": "Peitoral clavicular"},
    {"name": "Supino inclinado com barra", "muscle_group": "Peito", "muscle_subgroup": "Peitoral clavicular"},
    {"name": "Supino inclinado com halteres", "muscle_group": "Peito", "muscle_subgroup": "Peitoral clavicular"},
    {"name": "Supino inclinado máquina", "muscle_group": "Peito", "muscle_subgroup": "Peitoral clavicular"},
    {"name": "Crucifixo máquina", "muscle_group": "Peito", "muscle_subgroup": "Peitoral médio"},
    {"name": "Crucifixo reto com halteres", "muscle_group": "Peito", "muscle_subgroup": "Peitoral médio"},
    {"name": "Flexão de braço", "muscle_group": "Peito", "muscle_subgroup": "Peitoral médio"},
    {"name": "Supino reto com barra", "muscle_group": "Peito", "muscle_subgroup": "Peitoral médio"},
    {"name": "Supino reto com halteres", "muscle_group": "Peito", "muscle_subgroup": "Peitoral médio"},
    {"name": "Supino declinado com barra", "muscle_group": "Peito", "muscle_subgroup": "Peitoral inferior"},
    # Pernas
    {"name": "Agachamento hack", "muscle_group": "Pernas", "muscle_subgroup": "Quadríceps"},
    {"name": "Agachamento livre", "muscle_group": "Pernas", "muscle_subgroup": "Quadríceps"},
    {"name": "Cadeira extensora", "muscle_group": "Pernas", "muscle_subgroup": "Quadríceps"},
    {"name": "Leg press 45º", "muscle_group": "Pernas", "muscle_subgroup": "Quadríceps"},
    {"name": "Leg press sentado 90º", "muscle_group": "Pernas", "muscle_subgroup": "Quadríceps"},
    {"name": "Cadeira flexora", "muscle_group": "Pernas", "muscle_subgroup": "Posteriores de coxa"},
    {"name": "Mesa flexora", "muscle_group": "Pernas", "muscle_subgroup": "Posteriores de coxa"},
    {"name": "Posterior de coxa na polia", "muscle_group": "Pernas", "muscle_subgroup": "Posteriores de coxa"},
    {"name": "Stiff", "muscle_group": "Pernas", "muscle_subgroup": "Posteriores de coxa"},
    {"name": "Elevação pélvica", "muscle_group": "Pernas", "muscle_subgroup": "Glúteos"},
    {"name": "Elevação pélvica anilhas", "muscle_group": "Pernas", "muscle_subgroup": "Glúteos"},
    {"name": "Glúteo na polia", "muscle_group": "Pernas", "muscle_subgroup": "Glúteos"},
    {"name": "Cadeira adutora", "muscle_group": "Pernas", "muscle_subgroup": "Adutores"},
    {"name": "Cadeira abdutora", "muscle_group": "Pernas", "muscle_subgroup": "Abdutores"},
    {"name": "Panturrilha em pé", "muscle_group": "Pernas", "muscle_subgroup": "Panturrilha"},
    {"name": "Panturrilha sentado", "muscle_group": "Pernas", "muscle_subgroup": "Panturrilha"},
]


def normalize_exercise_name(name):
    """Normalize a name the same way exercise uniqueness is defined: trimmed, case-insensitive."""
    return name.strip().casefold()


def sync_exercise_library(session, library=EXERCISES):
    """Bring the database in line with the library without deleting anything.

    - library exercises missing from the database are created;
    - existing exercises keep their id and receive the library classification;
    - database exercises that are not in the library are left untouched.

    Returns a dict with the names that were created, updated and left untouched.
    """
    existing_by_name = {
        normalize_exercise_name(exercise.name): exercise
        for exercise in session.scalars(select(Exercise))
    }
    created, updated = [], []

    for entry in library:
        exercise = existing_by_name.pop(normalize_exercise_name(entry["name"]), None)
        if exercise is None:
            session.add(
                Exercise(
                    name=entry["name"],
                    muscle_group=entry["muscle_group"],
                    muscle_subgroup=entry["muscle_subgroup"],
                )
            )
            created.append(entry["name"])
        elif (exercise.muscle_group, exercise.muscle_subgroup) != (
            entry["muscle_group"],
            entry["muscle_subgroup"],
        ):
            exercise.muscle_group = entry["muscle_group"]
            exercise.muscle_subgroup = entry["muscle_subgroup"]
            updated.append(exercise.name)

    session.commit()
    not_in_library = sorted(exercise.name for exercise in existing_by_name.values())
    return {"created": created, "updated": updated, "not_in_library": not_in_library}


def _sort_key(text):
    # Sort accented names alongside their unaccented letters ("Elevação" next to
    # "Encolhimento"), and keep unclassified entries at the end of each level.
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    return (text == UNCLASSIFIED, without_accents.casefold())


def group_exercises(exercises):
    """Group exercises for display as [(group, [(subgroup, [exercise, ...]), ...]), ...].

    Groups and subgroups are sorted alphabetically (unclassified last) and
    exercises are sorted alphabetically inside each subgroup.
    """
    groups = {}
    for exercise in exercises:
        subgroups = groups.setdefault(exercise.muscle_group, {})
        subgroups.setdefault(exercise.muscle_subgroup, []).append(exercise)

    return [
        (
            group,
            [
                (subgroup, sorted(subgroup_exercises, key=lambda exercise: _sort_key(exercise.name)))
                for subgroup, subgroup_exercises in sorted(subgroups.items(), key=lambda item: _sort_key(item[0]))
            ],
        )
        for group, subgroups in sorted(groups.items(), key=lambda item: _sort_key(item[0]))
    ]


@click.command("sync-exercise-library")
@with_appcontext
def sync_exercise_library_command():
    """Create missing library exercises and update classifications (never deletes)."""
    result = sync_exercise_library(db.session)
    click.echo(f"Criados: {len(result['created'])}")
    for name in result["created"]:
        click.echo(f"  + {name}")
    click.echo(f"Classificação atualizada: {len(result['updated'])}")
    for name in result["updated"]:
        click.echo(f"  ~ {name}")
    if result["not_in_library"]:
        click.echo("Exercícios no banco que não estão na biblioteca (mantidos sem alteração):")
        for name in result["not_in_library"]:
            click.echo(f"  = {name}")
