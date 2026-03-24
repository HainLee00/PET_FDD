"""
Tests for DataCollector.
"""

import io
import csv
import pytest

from apd.data_collector import DataCollector


TEMP_TAG = "\\Data\\Blocks\\REACTOR\\Variables\\T\\"
FEED_TAG = "\\Data\\Streams\\FEED\\FmR\\"


def make_rows(n=5, dt=10.0, start=0.0):
    """Return a list of (time, {tag: value}) tuples."""
    rows = []
    for i in range(n):
        t = start + i * dt
        rows.append((t, {TEMP_TAG: 280.0 + i, FEED_TAG: 100.0 - i}))
    return rows


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

class TestDataCollectorRecording:
    def test_initial_state(self):
        dc = DataCollector()
        assert dc.row_count == 0
        assert dc.column_names == []

    def test_record_single_row(self):
        dc = DataCollector()
        dc.record(0.0, {TEMP_TAG: 280.0})
        assert dc.row_count == 1
        assert "time" in dc.column_names
        assert TEMP_TAG in dc.column_names

    def test_record_batch(self):
        dc = DataCollector()
        dc.record_batch(make_rows(10))
        assert dc.row_count == 10

    def test_fault_label_in_rows(self):
        dc = DataCollector(fault_label="my_fault")
        dc.record(0.0, {TEMP_TAG: 280.0})
        csv_str = dc.to_csv()
        reader = csv.DictReader(io.StringIO(csv_str))
        first = next(reader)
        assert first["fault"] == "my_fault"

    def test_clear(self):
        dc = DataCollector()
        dc.record_batch(make_rows(5))
        dc.clear()
        assert dc.row_count == 0

    def test_tag_filter(self):
        dc = DataCollector(tags=[TEMP_TAG])
        dc.record(0.0, {TEMP_TAG: 280.0, FEED_TAG: 100.0})
        csv_str = dc.to_csv()
        reader = csv.DictReader(io.StringIO(csv_str))
        first = next(reader)
        assert TEMP_TAG in first
        assert FEED_TAG not in first

    def test_extra_columns(self):
        dc = DataCollector(extra_columns={"run_id": "run_001"})
        dc.record(0.0, {TEMP_TAG: 280.0})
        csv_str = dc.to_csv()
        reader = csv.DictReader(io.StringIO(csv_str))
        first = next(reader)
        assert first["run_id"] == "run_001"


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

class TestCSVExport:
    def test_to_csv_empty(self):
        dc = DataCollector()
        assert dc.to_csv() == ""

    def test_to_csv_content(self):
        dc = DataCollector()
        dc.record_batch(make_rows(3))
        csv_str = dc.to_csv()
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 3

    def test_to_csv_time_values(self):
        dc = DataCollector()
        dc.record_batch(make_rows(3, dt=10.0))
        csv_str = dc.to_csv()
        reader = csv.DictReader(io.StringIO(csv_str))
        times = [float(row["time"]) for row in reader]
        assert times == pytest.approx([0.0, 10.0, 20.0])

    def test_to_csv_writes_file(self, tmp_path):
        dc = DataCollector()
        dc.record(0.0, {TEMP_TAG: 280.0})
        out_path = tmp_path / "output.csv"
        dc.to_csv(str(out_path))
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert TEMP_TAG in content


# ---------------------------------------------------------------------------
# DataFrame export
# ---------------------------------------------------------------------------

class TestDataFrameExport:
    def test_to_dataframe_requires_pandas(self):
        """If pandas is not available, to_dataframe raises ImportError."""
        import apd.data_collector as module
        original = module._PANDAS_AVAILABLE
        module._PANDAS_AVAILABLE = False
        try:
            dc = DataCollector()
            dc.record(0.0, {TEMP_TAG: 280.0})
            with pytest.raises(ImportError):
                dc.to_dataframe()
        finally:
            module._PANDAS_AVAILABLE = original

    def test_to_dataframe_empty(self):
        pytest.importorskip("pandas")
        dc = DataCollector()
        df = dc.to_dataframe()
        assert len(df) == 0

    def test_to_dataframe_shape(self):
        pd = pytest.importorskip("pandas")
        dc = DataCollector()
        dc.record_batch(make_rows(5))
        df = dc.to_dataframe()
        assert len(df) == 5
        assert "time" in df.columns
        assert TEMP_TAG in df.columns


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

class TestRepr:
    def test_repr(self):
        dc = DataCollector(fault_label="test_fault")
        r = repr(dc)
        assert "test_fault" in r
        assert "0" in r  # row count
