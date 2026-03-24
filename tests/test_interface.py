"""
Tests for APDInterface (mock mode only — no Aspen Plus licence required).
"""

import pytest
from apd.interface import APDInterface, MockAPDDocument


# ---------------------------------------------------------------------------
# APDInterface — lifecycle
# ---------------------------------------------------------------------------

class TestAPDInterfaceLifecycle:
    def test_open_and_close(self):
        apd = APDInterface()
        assert not apd.is_open
        apd.open()
        assert apd.is_open
        assert apd.mock_mode
        apd.close()
        assert not apd.is_open

    def test_context_manager(self):
        with APDInterface() as apd:
            assert apd.is_open
        assert not apd.is_open

    def test_operations_require_open(self):
        apd = APDInterface()
        with pytest.raises(RuntimeError):
            apd.run()
        with pytest.raises(RuntimeError):
            apd.get_variable("some_tag")

    def test_open_with_nonexistent_path_in_mock_mode(self):
        """In mock mode a non-existent file path is accepted without error."""
        with APDInterface("/nonexistent/file.apd") as apd:
            assert apd.is_open


# ---------------------------------------------------------------------------
# APDInterface — variable I/O (mock mode)
# ---------------------------------------------------------------------------

REACTOR_TEMP_TAG = "\\Data\\Blocks\\REACTOR\\Variables\\T\\"
FEED_FLOW_TAG = "\\Data\\Streams\\FEED\\FmR\\"


class TestAPDVariableIO:
    def test_get_known_variable(self):
        with APDInterface() as apd:
            temp = apd.get_variable(REACTOR_TEMP_TAG)
            assert isinstance(temp, float)
            assert temp == pytest.approx(280.0)

    def test_get_unknown_variable_returns_zero(self):
        with APDInterface() as apd:
            val = apd.get_variable("\\Unknown\\Tag\\")
            assert val == pytest.approx(0.0)

    def test_set_and_get_variable(self):
        with APDInterface() as apd:
            apd.set_variable(REACTOR_TEMP_TAG, 295.0)
            assert apd.get_variable(REACTOR_TEMP_TAG) == pytest.approx(295.0)

    def test_get_multiple(self):
        with APDInterface() as apd:
            result = apd.get_multiple([REACTOR_TEMP_TAG, FEED_FLOW_TAG])
            assert set(result.keys()) == {REACTOR_TEMP_TAG, FEED_FLOW_TAG}
            assert result[REACTOR_TEMP_TAG] == pytest.approx(280.0)
            assert result[FEED_FLOW_TAG] == pytest.approx(100.0)

    def test_run_pause_stop(self):
        with APDInterface() as apd:
            apd.run()
            assert apd._doc.is_running
            apd.pause()
            assert not apd._doc.is_running
            apd.run()
            apd.stop()
            assert not apd._doc.is_running

    def test_reinitialize_restores_defaults(self):
        with APDInterface() as apd:
            apd.set_variable(REACTOR_TEMP_TAG, 999.0)
            apd.reinitialize()
            assert apd.get_variable(REACTOR_TEMP_TAG) == pytest.approx(280.0)


# ---------------------------------------------------------------------------
# MockAPDDocument — direct unit tests
# ---------------------------------------------------------------------------

class TestMockAPDDocument:
    def test_default_values_present(self):
        doc = MockAPDDocument()
        for tag, expected in MockAPDDocument._DEFAULTS.items():
            assert doc.Tree(tag).Value == pytest.approx(expected)

    def test_set_via_tree(self):
        doc = MockAPDDocument()
        doc.Tree(REACTOR_TEMP_TAG).Value = 310.0
        assert doc.Tree(REACTOR_TEMP_TAG).Value == pytest.approx(310.0)

    def test_unknown_tag_creates_zero_variable(self):
        doc = MockAPDDocument()
        var = doc.Tree("\\Totally\\Unknown\\")
        assert var.Value == pytest.approx(0.0)
