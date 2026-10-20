from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, event, func, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base


# Marks an exercise whose muscle group or subgroup has not been classified yet.
# It is stored as a real value (not NULL) so it stays visible in the library.
UNCLASSIFIED = "XXXXX"

# Largest value of an SQLite INTEGER. Ids and positive integers above it cannot
# be stored or exist, and the driver raises OverflowError when given one.
SQLITE_MAX_INTEGER = 2**63 - 1

# Largest weight that fits the Numeric(8, 2) column. SQLite does not enforce
# the declared precision, so larger values would be stored inexactly (or as
# infinity) instead of being rejected.
MAX_WEIGHT_KG = Decimal("999999.99")

# Targets of an exercise in a template or a session: planned sets, and planned
# repetitions per set. Both are optional (NULL), so templates and sessions
# created before targets existed keep working without invented values, but
# they go together: both set or both NULL (targets_are_paired).
TARGET_SETS_MAX = 20
TARGET_REPETITIONS_MAX = 100


def targets_are_paired(target_sets: int | None, target_repetitions: int | None) -> bool:
    """Targets are set together (sets and repetitions per set) or not at all."""
    return (target_sets is None) == (target_repetitions is None)


def target_range_check(column_name: str, maximum: int) -> str:
    """SQL of the CHECK that keeps a target in range (NULL means no target).

    Shared by the models and by app.schema, so a new database and an upgraded
    one get the same rule.
    """
    return f"{column_name} BETWEEN 1 AND {maximum}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Workout(TimestampMixin, Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # NULL while the session is in progress; set once when it is completed.
    # A completed session is read-only.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workout_exercises: Mapped[list[WorkoutExercise]] = relationship(back_populates="workout", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str:
        return _validate_required_name(value)


class WorkoutTemplate(TimestampMixin, Base):
    """A reusable list of exercises from which workout sessions are started.

    Sessions copy the template's name and exercises when they start and keep no
    link to it, so changing or deleting a template never affects a session.
    """

    __tablename__ = "workout_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    # Same uniqueness rule as exercise names: trimmed and case-insensitive.
    __table_args__ = (
        Index("uq_workout_templates_normalized_name", func.lower(func.trim(name)), unique=True),
    )

    template_exercises: Mapped[list[WorkoutTemplateExercise]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkoutTemplateExercise.position",
    )

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str:
        return _validate_required_name(value)


class WorkoutTemplateExercise(TimestampMixin, Base):
    """An exercise of a template, at a given position."""

    __tablename__ = "workout_template_exercises"
    __table_args__ = (
        UniqueConstraint("template_id", "exercise_id", name="uq_workout_template_exercise"),
        UniqueConstraint("template_id", "position", name="uq_workout_template_exercise_position"),
        CheckConstraint("position > 0", name="ck_workout_template_exercise_position_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("workout_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    # Library exercises used by a template cannot be deleted, like those used by sessions.
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    target_sets: Mapped[int | None] = mapped_column(
        Integer,
        CheckConstraint(
            target_range_check("target_sets", TARGET_SETS_MAX),
            name="ck_workout_template_exercise_target_sets_range",
        ),
        nullable=True,
    )
    target_repetitions: Mapped[int | None] = mapped_column(
        Integer,
        CheckConstraint(
            target_range_check("target_repetitions", TARGET_REPETITIONS_MAX),
            name="ck_workout_template_exercise_target_repetitions_range",
        ),
        nullable=True,
    )

    template: Mapped[WorkoutTemplate] = relationship(back_populates="template_exercises")
    exercise: Mapped[Exercise] = relationship()

    @validates("position")
    def validate_position(self, _key: str, value: int) -> int:
        return _validate_positive_integer(value, "position")

    @validates("target_sets", "target_repetitions")
    def validate_targets(self, key: str, value: int | None) -> int | None:
        return _validate_target(value, key)


class Exercise(TimestampMixin, Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # server_default mirrors the column definition used by app.schema when the
    # column is added to an existing database.
    muscle_group: Mapped[str] = mapped_column(String(100), nullable=False, default=UNCLASSIFIED, server_default=UNCLASSIFIED)
    muscle_subgroup: Mapped[str] = mapped_column(String(100), nullable=False, default=UNCLASSIFIED, server_default=UNCLASSIFIED)

    __table_args__ = (
        Index("uq_exercises_normalized_name", func.lower(func.trim(name)), unique=True),
    )

    workout_exercises: Mapped[list[WorkoutExercise]] = relationship(back_populates="exercise", passive_deletes="all")

    @validates("name", "muscle_group", "muscle_subgroup")
    def validate_required_text(self, key: str, value: str) -> str:
        return _validate_required_name(value, key)


class WorkoutExercise(TimestampMixin, Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        UniqueConstraint("workout_id", "exercise_id", name="uq_workout_exercise"),
        UniqueConstraint("workout_id", "position", name="uq_workout_exercise_position"),
        CheckConstraint("position > 0", name="ck_workout_exercise_position_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Copied from the template when the session starts; never linked to it.
    # NULL for exercises added to the session by hand and for older sessions.
    target_sets: Mapped[int | None] = mapped_column(
        Integer,
        CheckConstraint(
            target_range_check("target_sets", TARGET_SETS_MAX),
            name="ck_workout_exercise_target_sets_range",
        ),
        nullable=True,
    )
    target_repetitions: Mapped[int | None] = mapped_column(
        Integer,
        CheckConstraint(
            target_range_check("target_repetitions", TARGET_REPETITIONS_MAX),
            name="ck_workout_exercise_target_repetitions_range",
        ),
        nullable=True,
    )

    workout: Mapped[Workout] = relationship(back_populates="workout_exercises")
    exercise: Mapped[Exercise] = relationship(back_populates="workout_exercises")
    sets: Mapped[list[WorkoutSet]] = relationship(back_populates="workout_exercise", cascade="all, delete-orphan", passive_deletes=True)

    @validates("position")
    def validate_position(self, _key: str, value: int) -> int:
        return _validate_positive_integer(value, "position")

    @validates("target_sets", "target_repetitions")
    def validate_targets(self, key: str, value: int | None) -> int | None:
        return _validate_target(value, key)


class WorkoutSet(TimestampMixin, Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        UniqueConstraint("workout_exercise_id", "position", name="uq_workout_set_position"),
        CheckConstraint("position > 0", name="ck_workout_set_position_positive"),
        CheckConstraint("repetitions > 0", name="ck_workout_set_repetitions_positive"),
        CheckConstraint("weight_kg >= 0", name="ck_workout_set_weight_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_exercise_id: Mapped[int] = mapped_column(ForeignKey("workout_exercises.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    workout_exercise: Mapped[WorkoutExercise] = relationship(back_populates="sets")

    @validates("position", "repetitions")
    def validate_positive_fields(self, key: str, value: int) -> int:
        return _validate_positive_integer(value, key)

    @validates("weight_kg")
    def validate_weight(self, _key: str, value: Decimal) -> Decimal:
        try:
            weight = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise ValueError("weight_kg must be a valid Decimal value") from error

        if not weight.is_finite() or weight < 0:
            raise ValueError("weight_kg must be greater than or equal to zero")
        if weight > MAX_WEIGHT_KG:
            raise ValueError(f"weight_kg must be at most {MAX_WEIGHT_KG}")
        if -weight.as_tuple().exponent > 2:
            raise ValueError("weight_kg must have at most two decimal places")
        return weight


def _validate_required_name(value: str, field_name: str = "name") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized_value


TARGET_MAXIMUMS = {"target_sets": TARGET_SETS_MAX, "target_repetitions": TARGET_REPETITIONS_MAX}


def _validate_target(value: int | None, field_name: str) -> int | None:
    """A target is optional; when present it is a whole number within its range."""
    if value is None:
        return None
    maximum = TARGET_MAXIMUMS[field_name]
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field_name} must be a whole number from 1 to {maximum}")
    return value


def _validate_positive_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    if value > SQLITE_MAX_INTEGER:
        raise ValueError(f"{field_name} is too large")
    return value


# The pair of targets is checked when the row is written, not in @validates:
# the two attributes are assigned one at a time, so a validator of one of them
# would still see the other one unset.


def _validate_target_pair(_mapper, _connection, item) -> None:
    if not targets_are_paired(item.target_sets, item.target_repetitions):
        raise ValueError("target_sets and target_repetitions must be set together")


def _validate_changed_target_pair(mapper, connection, item) -> None:
    # Only when a target changes: other updates (such as a new position when a
    # session is reordered) keep working on rows written before this rule.
    attributes = inspect(item).attrs
    if attributes.target_sets.history.has_changes() or attributes.target_repetitions.history.has_changes():
        _validate_target_pair(mapper, connection, item)


for _model_with_targets in (WorkoutTemplateExercise, WorkoutExercise):
    event.listen(_model_with_targets, "before_insert", _validate_target_pair)
    event.listen(_model_with_targets, "before_update", _validate_changed_target_pair)
