"""
Fault Simulator — injects process faults into an :class:`APDInterface` session.

Supported fault categories
--------------------------
* **Sensor faults** — bias, drift, or complete failure of a measurement tag.
* **Actuator faults** — stuck-at, bias, or gain error on a manipulated variable.
* **Process faults** — step or ramp disturbances on a process variable (e.g. feed
  flow, reactor temperature, cooling-water flow).

Each fault is defined as a :class:`FaultSpec` and is applied by calling
:meth:`FaultSimulator.apply_faults` once per simulation time step.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from .interface import APDInterface

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class FaultType(str, Enum):
    """High-level fault category."""

    SENSOR_BIAS = "sensor_bias"
    SENSOR_DRIFT = "sensor_drift"
    SENSOR_FAILURE = "sensor_failure"
    ACTUATOR_STUCK = "actuator_stuck"
    ACTUATOR_BIAS = "actuator_bias"
    ACTUATOR_GAIN = "actuator_gain"
    PROCESS_STEP = "process_step"
    PROCESS_RAMP = "process_ramp"
    NORMAL = "normal"


class FaultProfile(str, Enum):
    """Temporal shape of the fault magnitude."""

    STEP = "step"       # Instant step change at fault_start_time
    RAMP = "ramp"       # Linear ramp from 0 to full magnitude
    DRIFT = "drift"     # Slow exponential drift


# ---------------------------------------------------------------------------
# Fault specification dataclass
# ---------------------------------------------------------------------------

@dataclass
class FaultSpec:
    """
    Full specification of a single fault.

    Parameters
    ----------
    tag:
        Aspen variable path that is affected.
    fault_type:
        Category of the fault (see :class:`FaultType`).
    magnitude:
        Amplitude of the fault.  For bias/step faults this is the absolute
        offset added to the nominal value; for gain faults it is the
        multiplicative factor (e.g. ``0.8`` means 20 % gain reduction); for
        ``SENSOR_FAILURE`` it is the value the sensor is stuck at.
    start_time:
        Simulation time (seconds) at which the fault becomes active.
    duration:
        How long (seconds) the fault persists after *start_time*.
        ``None`` means the fault persists until the simulation ends.
    profile:
        Temporal shape (step, ramp, drift).
    ramp_duration:
        For :attr:`FaultProfile.RAMP`, the time (seconds) over which the
        fault magnitude ramps up from 0 to *magnitude*.
    label:
        Optional human-readable description for logging / CSV headers.
    """

    tag: str
    fault_type: FaultType
    magnitude: float
    start_time: float = 0.0
    duration: Optional[float] = None
    profile: FaultProfile = FaultProfile.STEP
    ramp_duration: float = 60.0
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = f"{self.fault_type.value}@{self.tag}"


# ---------------------------------------------------------------------------
# Fault Simulator
# ---------------------------------------------------------------------------

class FaultSimulator:
    """
    Applies fault specifications to an :class:`APDInterface` at each time step.

    Typical usage::

        specs = [
            FaultSpec(
                tag="\\\\Data\\\\Blocks\\\\REACTOR\\\\Variables\\\\T\\\\",
                fault_type=FaultType.PROCESS_STEP,
                magnitude=+10.0,   # +10 °C step
                start_time=300.0,  # fault starts at t = 300 s
                duration=600.0,
            )
        ]
        sim = FaultSimulator(apd_interface, specs)
        for t, row in sim.step_generator(dt=10.0, t_end=1200.0):
            ...  # row is {tag: perturbed_value}

    """

    def __init__(self, apd: APDInterface, specs: list[FaultSpec] | None = None):
        self._apd = apd
        self._specs: list[FaultSpec] = specs or []
        # Cache the nominal (pre-fault) values on first encounter
        self._nominal: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def add_fault(self, spec: FaultSpec) -> None:
        """Register an additional :class:`FaultSpec`."""
        self._specs.append(spec)

    def clear_faults(self) -> None:
        """Remove all registered fault specs and restore nominal values."""
        self._specs.clear()
        self._nominal.clear()

    @property
    def specs(self) -> list[FaultSpec]:
        return list(self._specs)

    # ------------------------------------------------------------------
    # Nominal value management
    # ------------------------------------------------------------------

    def _cache_nominal(self, tag: str) -> None:
        if tag not in self._nominal:
            self._nominal[tag] = self._apd.get_variable(tag)

    def restore_nominal(self) -> None:
        """Write all cached nominal values back to the simulation."""
        for tag, val in self._nominal.items():
            try:
                self._apd.set_variable(tag, val)
            except Exception as exc:
                logger.warning("Could not restore %s to %s: %s", tag, val, exc)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def _effective_magnitude(self, spec: FaultSpec, current_time: float) -> float:
        """
        Return the effective fault magnitude at *current_time*.

        Returns 0.0 if the fault is not yet active or has expired.
        """
        elapsed = current_time - spec.start_time
        if elapsed < 0:
            return 0.0
        if spec.duration is not None and elapsed > spec.duration:
            return 0.0

        if spec.profile == FaultProfile.STEP:
            return spec.magnitude

        if spec.profile == FaultProfile.RAMP:
            ramp = min(elapsed / max(spec.ramp_duration, 1e-9), 1.0)
            return spec.magnitude * ramp

        if spec.profile == FaultProfile.DRIFT:
            # Exponential approach: magnitude * (1 - exp(-elapsed / tau))
            tau = max(spec.ramp_duration, 1e-9)
            return spec.magnitude * (1.0 - math.exp(-elapsed / tau))

        return spec.magnitude  # fallback

    def apply_faults(self, current_time: float) -> dict[str, float]:
        """
        Compute and write the perturbed variable values at *current_time*.

        Returns a mapping ``{tag: perturbed_value}`` for every tag that has at
        least one active fault.  Tags with no active fault are not included.
        """
        active: dict[str, float] = {}

        for spec in self._specs:
            self._cache_nominal(spec.tag)
            eff = self._effective_magnitude(spec, current_time)

            nominal = self._nominal[spec.tag]
            perturbed = self._compute_perturbed(spec, nominal, eff)

            self._apd.set_variable(spec.tag, perturbed)
            active[spec.tag] = perturbed
            logger.debug(
                "t=%.1f  fault=%s  nominal=%.4f  perturbed=%.4f",
                current_time, spec.label, nominal, perturbed,
            )

        return active

    def _compute_perturbed(
        self, spec: FaultSpec, nominal: float, eff_magnitude: float
    ) -> float:
        """Apply fault logic and return the perturbed value."""
        if spec.fault_type in (FaultType.SENSOR_BIAS, FaultType.ACTUATOR_BIAS, FaultType.PROCESS_STEP, FaultType.PROCESS_RAMP):
            return nominal + eff_magnitude

        if spec.fault_type == FaultType.SENSOR_DRIFT:
            return nominal + eff_magnitude

        if spec.fault_type == FaultType.SENSOR_FAILURE:
            # Stuck-at fault — ignore nominal, return magnitude directly
            return spec.magnitude if eff_magnitude != 0.0 else nominal

        if spec.fault_type == FaultType.ACTUATOR_STUCK:
            # Actuator is stuck at the value it had when the fault started
            return self._nominal[spec.tag]

        if spec.fault_type == FaultType.ACTUATOR_GAIN:
            # Gain fault: output = nominal * magnitude factor
            if eff_magnitude != 0.0:
                return nominal * spec.magnitude
            return nominal

        return nominal + eff_magnitude  # default: additive offset

    # ------------------------------------------------------------------
    # Step generator
    # ------------------------------------------------------------------

    def step_generator(
        self,
        dt: float,
        t_end: float,
        t_start: float = 0.0,
        monitored_tags: list[str] | None = None,
    ):
        """
        Yield ``(time, data_row)`` for each simulation step.

        Parameters
        ----------
        dt:
            Simulation step size in seconds.
        t_end:
            End time of the simulation in seconds.
        t_start:
            Start time of the simulation (default ``0.0``).
        monitored_tags:
            List of APD variable tags to read at every step.  If *None* the
            tags referenced by the registered fault specs are used.

        Yields
        ------
        ``(float, dict[str, float])``
            The current simulation time and a dict mapping each monitored tag
            to its current (possibly perturbed) value.
        """
        if monitored_tags is None:
            monitored_tags = [s.tag for s in self._specs]
        # De-duplicate while preserving order
        seen: set[str] = set()
        unique_tags: list[str] = []
        for t in monitored_tags:
            if t not in seen:
                unique_tags.append(t)
                seen.add(t)

        current_time = t_start
        while current_time <= t_end + 1e-9:
            self.apply_faults(current_time)
            row = self._apd.get_multiple(unique_tags)
            row["time"] = current_time
            yield current_time, row
            current_time = round(current_time + dt, 10)
