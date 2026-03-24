"""
Data Collector — collects time-series data from an :class:`APDInterface`
session and exports it to CSV or pandas DataFrame.

The collector is intentionally decoupled from fault injection so it can be
used for normal-operation data collection as well.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# pandas is an optional runtime dependency
try:
    import pandas as pd  # type: ignore

    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False


class DataCollector:
    """
    Accumulates ``(time, {tag: value})`` rows and provides export utilities.

    Example::

        collector = DataCollector(tags=["\\\\Data\\\\Blocks\\\\REACTOR\\\\Variables\\\\T\\\\"])
        for t, row in sim.step_generator(dt=10.0, t_end=600.0):
            collector.record(t, row)
        collector.to_csv("results.csv")
    """

    def __init__(
        self,
        tags: list[str] | None = None,
        fault_label: str = "normal",
        extra_columns: dict[str, str] | None = None,
    ):
        """
        Parameters
        ----------
        tags:
            Variable tags to collect.  If *None* every key present in the
            first recorded row is collected.
        fault_label:
            A human-readable label stored in the ``fault`` column of the
            output (e.g. ``"normal"``, ``"reactor_temp_bias_+10C"``).
        extra_columns:
            Static metadata columns added to every row, e.g.
            ``{"run_id": "run_001", "apd_file": "pet.apd"}``.
        """
        self._tags: list[str] | None = tags
        self.fault_label = fault_label
        self._extra: dict[str, str] = extra_columns or {}
        self._rows: list[dict] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, time: float, data: dict[str, float]) -> None:
        """
        Store a single time-step snapshot.

        Parameters
        ----------
        time:
            Simulation time in seconds.
        data:
            Mapping of ``{tag: value}`` from the current step.
        """
        row: dict = {"time": time, "fault": self.fault_label}
        row.update(self._extra)

        if self._tags is not None:
            for tag in self._tags:
                row[tag] = data.get(tag, float("nan"))
        else:
            row.update({k: v for k, v in data.items() if k != "time"})

        self._rows.append(row)

    def record_batch(self, rows: Iterable[tuple[float, dict[str, float]]]) -> None:
        """Record an iterable of ``(time, data_dict)`` pairs."""
        for time, data in rows:
            self.record(time, data)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_csv(
        self,
        path: str | Path | None = None,
        *,
        encoding: str = "utf-8",
    ) -> str:
        """
        Write recorded data to CSV.

        Parameters
        ----------
        path:
            Destination file path.  If *None* the CSV content is returned
            as a string (useful for in-memory / Streamlit downloads).
        encoding:
            File encoding (ignored when *path* is *None*).

        Returns
        -------
        str
            The CSV content as a string (always, even when written to disk).
        """
        if not self._rows:
            logger.warning("DataCollector.to_csv called with no recorded rows")
            return ""

        fieldnames = list(self._rows[0].keys())
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(self._rows)
        csv_content = output.getvalue()

        if path is not None:
            Path(path).write_text(csv_content, encoding=encoding)
            logger.info("Data saved to %s (%d rows)", path, len(self._rows))

        return csv_content

    def to_dataframe(self):
        """
        Return the collected data as a :class:`pandas.DataFrame`.

        Raises
        ------
        ImportError
            If pandas is not installed.
        """
        if not _PANDAS_AVAILABLE:
            raise ImportError(
                "pandas is required for DataCollector.to_dataframe(). "
                "Install it with: pip install pandas"
            )
        if not self._rows:
            return pd.DataFrame()
        return pd.DataFrame(self._rows)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Discard all recorded rows."""
        self._rows.clear()

    @property
    def row_count(self) -> int:
        """Number of rows currently stored."""
        return len(self._rows)

    @property
    def column_names(self) -> list[str]:
        """Column names inferred from the first recorded row."""
        if not self._rows:
            return []
        return list(self._rows[0].keys())

    def __repr__(self) -> str:
        return (
            f"DataCollector(fault_label={self.fault_label!r}, "
            f"rows={self.row_count})"
        )
