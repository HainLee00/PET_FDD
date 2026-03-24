"""
APD Interface — Python bridge to Aspen Plus Dynamics via COM automation.

On non-Windows environments (or when pywin32 is not installed) the interface
falls back to a :class:`MockAPDDocument` so that the rest of the framework
can be exercised without a live Aspen Plus Dynamics installation.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import win32com — only available on Windows with pywin32 installed
# ---------------------------------------------------------------------------
try:
    import win32com.client  # type: ignore

    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False
    logger.warning(
        "pywin32 is not available. APDInterface will run in mock mode. "
        "Install pywin32 on Windows to connect to a live Aspen Plus Dynamics session."
    )


# ---------------------------------------------------------------------------
# Mock document (used when pywin32 / Windows is not available)
# ---------------------------------------------------------------------------

class MockAPDVariable:
    """Minimal stand-in for an Aspen Plus Dynamics variable node."""

    def __init__(self, name: str, value: float = 0.0):
        self.name = name
        self._value = value

    @property
    def Value(self) -> float:  # noqa: N802  # PascalCase matches the COM API convention
        return self._value

    @Value.setter
    def Value(self, v: float) -> None:  # noqa: N802  # PascalCase matches the COM API convention
        self._value = float(v)


class MockAPDDocument:
    """
    Minimal mock of the Aspen Plus Dynamics COM document object.

    Variable names mirror common PET depolymerization process tags so that
    fault-injection and data-collection logic can be tested without Aspen.
    """

    # Default steady-state values for a PET depolymerisation reactor
    _DEFAULTS: dict[str, float] = {
        # Reactor
        "\\Data\\Streams\\FEED\\FmR\\": 100.0,      # Feed mass flow  [kg/h]
        "\\Data\\Streams\\PROD\\FmR\\": 98.5,       # Product mass flow [kg/h]
        "\\Data\\Blocks\\REACTOR\\Variables\\T\\": 280.0,   # Reactor temp [°C]
        "\\Data\\Blocks\\REACTOR\\Variables\\P\\": 1.0,     # Reactor pressure [bar]
        "\\Data\\Blocks\\REACTOR\\Variables\\L\\": 0.65,    # Liquid level [-]
        "\\Data\\Blocks\\REACTOR\\Variables\\XA\\": 0.92,   # Conversion [-]
        # Heat exchanger
        "\\Data\\Blocks\\HX\\Variables\\Q\\": 250.0,        # Duty [kW]
        "\\Data\\Blocks\\HX\\Variables\\T_hot_out\\": 220.0,# Hot side outlet [°C]
        # Cooling water
        "\\Data\\Streams\\CW_IN\\FmR\\": 500.0,    # CW flow [kg/h]
        "\\Data\\Streams\\CW_OUT\\T\\": 35.0,      # CW outlet temp [°C]
        # Catalyst
        "\\Data\\Streams\\CAT\\FmR\\": 2.0,        # Catalyst flow [kg/h]
    }

    def __init__(self, path: str | None = None):
        self._path = path
        self._variables: dict[str, MockAPDVariable] = {
            tag: MockAPDVariable(tag, val)
            for tag, val in self._DEFAULTS.items()
        }
        self._running = False
        logger.info("MockAPDDocument initialised (path=%s)", path)

    # ------------------------------------------------------------------
    # Simulation control
    # ------------------------------------------------------------------

    def Run(self) -> None:  # noqa: N802
        self._running = True
        logger.debug("Mock: simulation started")

    def Pause(self) -> None:  # noqa: N802
        self._running = False
        logger.debug("Mock: simulation paused")

    def Stop(self) -> None:  # noqa: N802
        self._running = False
        logger.debug("Mock: simulation stopped")

    def Reinitialize(self) -> None:  # noqa: N802
        for tag, default_val in self._DEFAULTS.items():
            self._variables[tag].Value = default_val
        logger.debug("Mock: simulation re-initialised to steady state")

    # ------------------------------------------------------------------
    # Variable access (mimics the COM tree traversal)
    # ------------------------------------------------------------------

    def Tree(self, tag: str) -> MockAPDVariable:  # noqa: N802
        """Return the variable node for *tag*, creating a zero-valued one if unknown."""
        if tag not in self._variables:
            self._variables[tag] = MockAPDVariable(tag)
        return self._variables[tag]

    def Close(self) -> None:  # noqa: N802
        logger.debug("Mock: document closed")

    # Convenience property so callers can inspect open status
    @property
    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class APDInterface:
    """
    High-level wrapper around the Aspen Plus Dynamics COM document.

    Usage::

        with APDInterface("C:/Simulations/pet_depolymerization.apd") as apd:
            apd.run()
            temp = apd.get_variable("\\\\Data\\\\Blocks\\\\REACTOR\\\\Variables\\\\T\\\\")
            apd.set_variable("\\\\Data\\\\Streams\\\\FEED\\\\FmR\\\\", 110.0)

    When ``pywin32`` is unavailable the interface automatically uses
    :class:`MockAPDDocument` so that downstream logic remains testable.
    """

    #: COM ProgID for Aspen Plus Dynamics
    _COM_PROGID = "Apwn.Document"

    def __init__(self, apd_path: str | Path | None = None):
        self._path: str | None = str(apd_path) if apd_path else None
        self._doc: Any = None
        self._mock_mode: bool = not _WIN32_AVAILABLE

    # ------------------------------------------------------------------
    # Context manager helpers
    # ------------------------------------------------------------------

    def __enter__(self) -> "APDInterface":
        self.open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the APD file and attach to Aspen Plus Dynamics."""
        if self._mock_mode:
            self._doc = MockAPDDocument(self._path)
            logger.info("APDInterface opened in mock mode")
            return

        try:
            self._doc = win32com.client.Dispatch(self._COM_PROGID)
            if self._path:
                if not Path(self._path).exists():
                    raise FileNotFoundError(f"APD file not found: {self._path}")
                self._doc.Open(self._path)
                logger.info("Opened APD file: %s", self._path)
        except Exception as exc:
            logger.error("Failed to open APD via COM: %s", exc)
            raise

    def close(self) -> None:
        """Pause the simulation and release the COM object."""
        if self._doc is not None:
            try:
                self._doc.Pause()
                self._doc.Close()
            except Exception:
                pass
            self._doc = None

    # ------------------------------------------------------------------
    # Simulation control
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start / resume the dynamic simulation."""
        self._require_open()
        self._doc.Run()
        logger.debug("Simulation started")

    def pause(self) -> None:
        """Pause the dynamic simulation."""
        self._require_open()
        self._doc.Pause()
        logger.debug("Simulation paused")

    def stop(self) -> None:
        """Stop the dynamic simulation."""
        self._require_open()
        self._doc.Stop()
        logger.debug("Simulation stopped")

    def reinitialize(self) -> None:
        """Re-initialise the simulation to the saved steady state."""
        self._require_open()
        self._doc.Reinitialize()
        logger.debug("Simulation re-initialised")

    # ------------------------------------------------------------------
    # Variable I/O
    # ------------------------------------------------------------------

    def get_variable(self, tag: str) -> float:
        """
        Read the current value of an Aspen variable identified by *tag*.

        Parameters
        ----------
        tag:
            Full Aspen variable path, e.g.
            ``"\\\\Data\\\\Blocks\\\\REACTOR\\\\Variables\\\\T\\\\"``
        """
        self._require_open()
        try:
            if self._mock_mode:
                return float(self._doc.Tree(tag).Value)
            node = self._doc.Tree.FindNode(tag)
            if node is None:
                raise KeyError(f"Variable not found in APD tree: {tag}")
            return float(node.Value)
        except Exception as exc:
            logger.error("get_variable(%s) failed: %s", tag, exc)
            raise

    def set_variable(self, tag: str, value: float) -> None:
        """
        Write *value* to an Aspen variable.

        Parameters
        ----------
        tag:
            Full Aspen variable path.
        value:
            New numeric value to assign.
        """
        self._require_open()
        try:
            if self._mock_mode:
                self._doc.Tree(tag).Value = value
            else:
                node = self._doc.Tree.FindNode(tag)
                if node is None:
                    raise KeyError(f"Variable not found in APD tree: {tag}")
                node.Value = value
            logger.debug("set_variable(%s) = %s", tag, value)
        except Exception as exc:
            logger.error("set_variable(%s, %s) failed: %s", tag, value, exc)
            raise

    def get_multiple(self, tags: list[str]) -> dict[str, float]:
        """Read multiple variables at once and return a ``{tag: value}`` dict."""
        return {tag: self.get_variable(tag) for tag in tags}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def mock_mode(self) -> bool:
        """``True`` when operating without a real Aspen Plus Dynamics installation."""
        return self._mock_mode

    @property
    def is_open(self) -> bool:
        return self._doc is not None

    def _require_open(self) -> None:
        if self._doc is None:
            raise RuntimeError("APDInterface is not open. Call open() first.")
