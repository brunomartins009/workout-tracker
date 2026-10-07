from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database import Base


# Marks an exercise whose muscle group or subgroup has not been classified yet.
# It is stored as a real value (not NULL) so it stays visible in the library.
UNCLASSIFIED = "XXXXX"


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

    workout_exercises: Mapped[list[WorkoutExercise]] = relationship(back_populates="workout", cascade="all, delete-orphan", passive_deletes=True)

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str:
        return _validate_required_name(value)


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

    workout: Mapped[Workout] = relationship(back_populates="workout_exercises")
    exercise: Mapped[Exercise] = relationship(back_populates="workout_exercises")
    sets: Mapped[list[WorkoutSet]] = relationship(back_populates="workout_exercise", cascade="all, delete-orphan", passive_deletes=True)

    @validates("position")
    def validate_position(self, _key: str, value: int) -> int:
        return _validate_positive_integer(value, "position")


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


def _validate_positive_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value
