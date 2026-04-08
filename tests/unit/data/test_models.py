"""Unit tests for domain Pydantic models."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from broombroom.data.models import (
    Compound,
    DriverProbability,
    QualiResult,
    RaceEvent,
    RacePrediction,
    RaceResult,
    SeasonSchedule,
    Stint,
    TyreStrategy,
)
from broombroom.data.models.analysis import DegradationResult, DriverRadarMetrics
from broombroom.data.models.circuit import CircuitProfile

# ── RaceEvent ─────────────────────────────────────────────────────────────────


class TestRaceEvent:
    def test_basic_construction(self) -> None:
        e = RaceEvent(
            season=2024,
            round_number=5,
            event_name="Monaco Grand Prix",
            circuit_key="monaco",
            country="Monaco",
            locality="Monte-Carlo",
            date=date(2024, 5, 26),
        )
        assert e.sprint is False
        assert e.circuit_key == "monaco"

    def test_invalid_season(self) -> None:
        with pytest.raises(ValidationError):
            RaceEvent(
                season=1800,
                round_number=1,
                event_name="X",
                circuit_key="x",
                country="X",
                locality="X",
                date=date(2024, 1, 1),
            )


class TestSeasonSchedule:
    def test_get_round(self) -> None:
        e = RaceEvent(
            season=2024,
            round_number=3,
            event_name="Australian GP",
            circuit_key="albert_park",
            country="Australia",
            locality="Melbourne",
            date=date(2024, 3, 24),
        )
        schedule = SeasonSchedule(season=2024, events=[e])
        assert schedule.get_round(3) is e
        assert schedule.get_round(99) is None
        assert schedule.rounds == 1


# ── RaceResult ────────────────────────────────────────────────────────────────


class TestRaceResult:
    def test_classified_finish(self) -> None:
        r = RaceResult(
            season=2024,
            round_number=1,
            driver_id="max_verstappen",
            driver_code="ver",
            constructor_id="red_bull",
            grid_position=1,
            finish_position=1,
            status="Finished",
            points=25.0,
            fastest_lap=True,
        )
        assert r.classified is True
        assert r.dnf is False
        assert r.driver_code == "VER"  # auto-uppercased

    def test_dnf(self) -> None:
        r = RaceResult(
            season=2024,
            round_number=1,
            driver_id="lando_norris",
            driver_code="NOR",
            constructor_id="mclaren",
            grid_position=3,
            finish_position=None,
            status="Accident",
            points=0.0,
        )
        assert r.classified is False
        assert r.dnf is True

    def test_negative_points_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RaceResult(
                season=2024,
                round_number=1,
                driver_id="x",
                driver_code="XXX",
                constructor_id="y",
                grid_position=1,
                finish_position=1,
                status="Finished",
                points=-1.0,
            )


# ── QualiResult ───────────────────────────────────────────────────────────────


class TestQualiResult:
    def test_best_time_q3(self) -> None:
        q = QualiResult(
            season=2024,
            round_number=1,
            driver_id="x",
            driver_code="VER",
            constructor_id="red_bull",
            position=1,
            q1_time=timedelta(minutes=1, seconds=30),
            q2_time=timedelta(minutes=1, seconds=29),
            q3_time=timedelta(minutes=1, seconds=28),
        )
        assert q.best_time == timedelta(minutes=1, seconds=28)

    def test_best_time_no_q3(self) -> None:
        q = QualiResult(
            season=2024,
            round_number=1,
            driver_id="x",
            driver_code="NOR",
            constructor_id="mclaren",
            position=11,
            q1_time=timedelta(minutes=1, seconds=30),
            q2_time=timedelta(minutes=1, seconds=29),
        )
        assert q.best_time == timedelta(minutes=1, seconds=29)

    def test_q3_without_q2_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QualiResult(
                season=2024,
                round_number=1,
                driver_id="x",
                driver_code="XXX",
                constructor_id="y",
                position=1,
                q1_time=timedelta(minutes=1, seconds=30),
                q3_time=timedelta(minutes=1, seconds=28),
            )

    def test_missing_all_times_allowed(self) -> None:
        # DNS / no time set is valid
        q = QualiResult(
            season=2024,
            round_number=1,
            driver_id="x",
            driver_code="XXX",
            constructor_id="y",
            position=20,
        )
        assert q.best_time is None


# ── Compound ──────────────────────────────────────────────────────────────────


class TestCompound:
    def test_from_fastf1(self) -> None:
        assert Compound.from_fastf1("SOFT") == Compound.SOFT
        assert Compound.from_fastf1("Inter") == Compound.INTERMEDIATE
        assert Compound.from_fastf1(None) == Compound.UNKNOWN
        assert Compound.from_fastf1("UNKNOWN_THING") == Compound.UNKNOWN

    def test_colors_defined(self) -> None:
        for c in Compound:
            assert c.color.startswith("#")

    def test_is_slick(self) -> None:
        assert Compound.SOFT.is_slick is True
        assert Compound.WET.is_slick is False
        assert Compound.INTERMEDIATE.is_slick is False


# ── Stint ─────────────────────────────────────────────────────────────────────


class TestStint:
    def test_length(self) -> None:
        s = Stint(
            driver_code="VER",
            stint_number=1,
            compound=Compound.SOFT,
            start_lap=1,
            end_lap=20,
            tyre_age_at_start=0,
        )
        assert s.length == 20
        assert s.max_tyre_age == 19

    def test_end_before_start_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Stint(
                driver_code="VER",
                stint_number=1,
                compound=Compound.MEDIUM,
                start_lap=20,
                end_lap=10,
                tyre_age_at_start=0,
            )

    def test_single_lap_stint(self) -> None:
        s = Stint(
            driver_code="VER",
            stint_number=2,
            compound=Compound.HARD,
            start_lap=5,
            end_lap=5,
            tyre_age_at_start=3,
        )
        assert s.length == 1


class TestTyreStrategy:
    def test_stop_count(self) -> None:
        def _stint(num: int, compound: Compound, start: int, end: int) -> Stint:
            return Stint(
                driver_code="NOR",
                stint_number=num,
                compound=compound,
                start_lap=start,
                end_lap=end,
                tyre_age_at_start=0,
            )

        stints = [
            _stint(1, Compound.SOFT, 1, 20),
            _stint(2, Compound.MEDIUM, 21, 40),
            _stint(3, Compound.HARD, 41, 57),
        ]
        strategy = TyreStrategy(driver_code="NOR", stints=stints)
        assert strategy.stop_count == 2
        assert strategy.compounds_used == [Compound.SOFT, Compound.MEDIUM, Compound.HARD]


# ── CircuitProfile ────────────────────────────────────────────────────────────


class TestCircuitProfile:
    def test_construction(self) -> None:
        p = CircuitProfile(
            circuit_key="monaco",
            name="Circuit de Monaco",
            low_speed_corner_pct=0.7,
            medium_speed_corner_pct=0.2,
            high_speed_corner_pct=0.1,
            total_corners=19,
            drs_zone_count=1,
            lap_length_km=3.337,
            estimated_straight_length_km=0.5,
        )
        assert p.implied_downforce_level == "medium"  # default


# ── DegradationResult ─────────────────────────────────────────────────────────


class TestDegradationResult:
    def test_valid(self) -> None:
        d = DegradationResult(
            driver_code="VER",
            compound=Compound.SOFT,
            circuit_key="monza",
            sample_count=15,
            coefficients=[0.05, 0.01, 90.0],
            r_squared=0.92,
            predicted_delta_at_lap={1: 0.0, 10: 0.6, 20: 1.5},
        )
        assert d.r_squared == 0.92


# ── DriverRadarMetrics ────────────────────────────────────────────────────────


class TestDriverRadarMetrics:
    def test_all_scores_in_range(self) -> None:
        m = DriverRadarMetrics(
            driver_code="LEC",
            sessions_used=5,
            max_speed_score=0.95,
            braking_consistency=0.88,
            corner_entry_score=0.91,
            corner_exit_score=0.87,
            sector_1_score=0.93,
            sector_2_score=0.89,
            sector_3_score=0.85,
        )
        assert all(
            0.0 <= v <= 1.0
            for v in [
                m.max_speed_score,
                m.braking_consistency,
                m.corner_entry_score,
                m.corner_exit_score,
                m.sector_1_score,
                m.sector_2_score,
                m.sector_3_score,
            ]
        )

    def test_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DriverRadarMetrics(
                driver_code="LEC",
                sessions_used=5,
                max_speed_score=1.5,  # > 1.0
                braking_consistency=0.88,
                corner_entry_score=0.91,
                corner_exit_score=0.87,
                sector_1_score=0.93,
                sector_2_score=0.89,
                sector_3_score=0.85,
            )


# ── RacePrediction ────────────────────────────────────────────────────────────


class TestRacePrediction:
    def _make_driver(self, code: str, win_p: float) -> DriverProbability:
        return DriverProbability(
            driver_id=code.lower(),
            driver_code=code,
            constructor_id="team",
            win_probability=win_p,
            podium_probability=min(win_p * 2, 1.0),
            points_probability=min(win_p * 5, 1.0),
            expected_position=1.0 + (1.0 - win_p) * 19,
            position_ci_lower=1.0,
            position_ci_upper=5.0,
        )

    def test_predicted_winner(self) -> None:
        pred = RacePrediction(
            season=2025,
            round_number=8,
            circuit_key="monaco",
            model_name="lightgbm_outcome",
            model_version="1.0",
            driver_predictions=[
                self._make_driver("VER", 0.45),
                self._make_driver("NOR", 0.25),
                self._make_driver("LEC", 0.20),
            ],
        )
        assert pred.predicted_winner is not None
        assert pred.predicted_winner.driver_code == "VER"
        assert len(pred.caveats) >= 1

    def test_ci_ordering_enforced(self) -> None:
        with pytest.raises(ValidationError):
            DriverProbability(
                driver_id="ver",
                driver_code="VER",
                constructor_id="red_bull",
                win_probability=0.4,
                podium_probability=0.7,
                points_probability=0.9,
                expected_position=1.5,
                position_ci_lower=5.0,  # lower > upper — invalid
                position_ci_upper=2.0,
            )
