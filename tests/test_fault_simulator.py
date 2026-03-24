"""
Tests for FaultSimulator.
"""

import math
import pytest

from apd.interface import APDInterface
from apd.fault_simulator import (
    FaultSimulator,
    FaultSpec,
    FaultType,
    FaultProfile,
)

TEMP_TAG = "\\Data\\Blocks\\REACTOR\\Variables\\T\\"
FEED_TAG = "\\Data\\Streams\\FEED\\FmR\\"
CW_TAG = "\\Data\\Streams\\CW_IN\\FmR\\"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_apd():
    apd = APDInterface()
    apd.open()
    return apd


def make_step_spec(tag=TEMP_TAG, magnitude=10.0, start_time=0.0, duration=None):
    return FaultSpec(
        tag=tag,
        fault_type=FaultType.PROCESS_STEP,
        magnitude=magnitude,
        start_time=start_time,
        duration=duration,
        profile=FaultProfile.STEP,
    )


# ---------------------------------------------------------------------------
# FaultSpec
# ---------------------------------------------------------------------------

class TestFaultSpec:
    def test_label_auto_generated(self):
        spec = FaultSpec(tag=TEMP_TAG, fault_type=FaultType.SENSOR_BIAS, magnitude=5.0)
        assert TEMP_TAG in spec.label or "sensor_bias" in spec.label

    def test_label_custom(self):
        spec = FaultSpec(
            tag=TEMP_TAG, fault_type=FaultType.SENSOR_BIAS, magnitude=5.0,
            label="my_custom_label"
        )
        assert spec.label == "my_custom_label"


# ---------------------------------------------------------------------------
# Effective magnitude
# ---------------------------------------------------------------------------

class TestEffectiveMagnitude:
    def setup_method(self):
        self.apd = make_apd()
        self.sim = FaultSimulator(self.apd)

    def teardown_method(self):
        self.apd.close()

    def test_step_before_start_is_zero(self):
        spec = make_step_spec(start_time=300.0)
        assert self.sim._effective_magnitude(spec, 0.0) == pytest.approx(0.0)
        assert self.sim._effective_magnitude(spec, 299.9) == pytest.approx(0.0)

    def test_step_at_and_after_start(self):
        spec = make_step_spec(magnitude=10.0, start_time=300.0)
        assert self.sim._effective_magnitude(spec, 300.0) == pytest.approx(10.0)
        assert self.sim._effective_magnitude(spec, 1000.0) == pytest.approx(10.0)

    def test_step_after_duration_is_zero(self):
        spec = make_step_spec(magnitude=10.0, start_time=300.0, duration=200.0)
        assert self.sim._effective_magnitude(spec, 501.0) == pytest.approx(0.0)

    def test_ramp_profile(self):
        spec = FaultSpec(
            tag=TEMP_TAG, fault_type=FaultType.PROCESS_RAMP,
            magnitude=10.0, start_time=0.0, profile=FaultProfile.RAMP,
            ramp_duration=100.0,
        )
        assert self.sim._effective_magnitude(spec, 0.0) == pytest.approx(0.0)
        assert self.sim._effective_magnitude(spec, 50.0) == pytest.approx(5.0)
        assert self.sim._effective_magnitude(spec, 100.0) == pytest.approx(10.0)
        assert self.sim._effective_magnitude(spec, 200.0) == pytest.approx(10.0)

    def test_drift_profile(self):
        spec = FaultSpec(
            tag=TEMP_TAG, fault_type=FaultType.SENSOR_DRIFT,
            magnitude=8.0, start_time=0.0, profile=FaultProfile.DRIFT,
            ramp_duration=300.0,
        )
        # At t=0, drift = 0
        assert self.sim._effective_magnitude(spec, 0.0) == pytest.approx(0.0, abs=1e-6)
        # At t=tau the drift should be magnitude*(1-1/e) ≈ 63.2% of magnitude
        val_at_tau = self.sim._effective_magnitude(spec, 300.0)
        expected = 8.0 * (1 - math.exp(-1.0))
        assert val_at_tau == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# apply_faults
# ---------------------------------------------------------------------------

class TestApplyFaults:
    def setup_method(self):
        self.apd = make_apd()

    def teardown_method(self):
        self.apd.close()

    def test_no_fault_when_before_start(self):
        spec = make_step_spec(magnitude=10.0, start_time=300.0)
        sim = FaultSimulator(self.apd, [spec])
        nominal = self.apd.get_variable(TEMP_TAG)
        sim.apply_faults(0.0)
        assert self.apd.get_variable(TEMP_TAG) == pytest.approx(nominal)

    def test_process_step_adds_magnitude(self):
        spec = make_step_spec(magnitude=10.0, start_time=0.0)
        sim = FaultSimulator(self.apd, [spec])
        nominal = self.apd.get_variable(TEMP_TAG)
        sim.apply_faults(0.0)
        assert self.apd.get_variable(TEMP_TAG) == pytest.approx(nominal + 10.0)

    def test_sensor_failure_stuck_at(self):
        spec = FaultSpec(
            tag=TEMP_TAG, fault_type=FaultType.SENSOR_FAILURE,
            magnitude=999.0, start_time=0.0,
        )
        sim = FaultSimulator(self.apd, [spec])
        sim.apply_faults(0.0)
        assert self.apd.get_variable(TEMP_TAG) == pytest.approx(999.0)

    def test_actuator_gain(self):
        spec = FaultSpec(
            tag=FEED_TAG, fault_type=FaultType.ACTUATOR_GAIN,
            magnitude=0.8, start_time=0.0,
        )
        sim = FaultSimulator(self.apd, [spec])
        nominal = self.apd.get_variable(FEED_TAG)
        sim.apply_faults(0.0)
        assert self.apd.get_variable(FEED_TAG) == pytest.approx(nominal * 0.8)

    def test_restore_nominal(self):
        spec = make_step_spec(magnitude=50.0, start_time=0.0)
        sim = FaultSimulator(self.apd, [spec])
        nominal = self.apd.get_variable(TEMP_TAG)
        sim.apply_faults(0.0)
        assert self.apd.get_variable(TEMP_TAG) != pytest.approx(nominal)
        sim.restore_nominal()
        assert self.apd.get_variable(TEMP_TAG) == pytest.approx(nominal)

    def test_multiple_faults(self):
        specs = [
            make_step_spec(tag=TEMP_TAG, magnitude=5.0, start_time=0.0),
            make_step_spec(tag=FEED_TAG, magnitude=10.0, start_time=0.0),
        ]
        sim = FaultSimulator(self.apd, specs)
        nom_t = self.apd.get_variable(TEMP_TAG)
        nom_f = self.apd.get_variable(FEED_TAG)
        sim.apply_faults(0.0)
        assert self.apd.get_variable(TEMP_TAG) == pytest.approx(nom_t + 5.0)
        assert self.apd.get_variable(FEED_TAG) == pytest.approx(nom_f + 10.0)


# ---------------------------------------------------------------------------
# step_generator
# ---------------------------------------------------------------------------

class TestStepGenerator:
    def setup_method(self):
        self.apd = make_apd()

    def teardown_method(self):
        self.apd.close()

    def test_step_count(self):
        sim = FaultSimulator(self.apd, [])
        rows = list(sim.step_generator(dt=10.0, t_end=100.0, monitored_tags=[TEMP_TAG]))
        # t = 0, 10, 20, ..., 100  → 11 rows
        assert len(rows) == 11

    def test_time_column_in_row(self):
        sim = FaultSimulator(self.apd, [])
        times = [t for t, _ in sim.step_generator(dt=10.0, t_end=50.0, monitored_tags=[TEMP_TAG])]
        assert times[0] == pytest.approx(0.0)
        assert times[-1] == pytest.approx(50.0)

    def test_fault_applied_after_start_time(self):
        spec = make_step_spec(magnitude=10.0, start_time=50.0)
        sim = FaultSimulator(self.apd, [spec])
        nominal = 280.0  # known default
        rows = dict(sim.step_generator(dt=10.0, t_end=100.0, monitored_tags=[TEMP_TAG]))
        # Before fault start — value should be nominal
        assert rows[40.0][TEMP_TAG] == pytest.approx(nominal)
        # At and after fault start
        assert rows[50.0][TEMP_TAG] == pytest.approx(nominal + 10.0)
        assert rows[100.0][TEMP_TAG] == pytest.approx(nominal + 10.0)

    def test_add_and_clear_faults(self):
        sim = FaultSimulator(self.apd, [])
        assert len(sim.specs) == 0
        spec = make_step_spec()
        sim.add_fault(spec)
        assert len(sim.specs) == 1
        sim.clear_faults()
        assert len(sim.specs) == 0
