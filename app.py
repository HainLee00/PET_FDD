"""
PET FDD Streamlit App
=====================
Upload an Aspen Plus Dynamics (.apd) file, configure fault scenarios, run the
dynamic simulation, and download the generated fault-labelled dataset.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st
import yaml

# Ensure the project root is on the import path when launched from a
# different working directory.
sys.path.insert(0, str(Path(__file__).parent))

from apd.interface import APDInterface
from apd.fault_simulator import FaultSimulator, FaultSpec, FaultType, FaultProfile
from apd.data_collector import DataCollector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "config" / "fault_config.yaml"


@st.cache_data
def load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_uploaded_apd(uploaded_file) -> str:
    """Save a Streamlit UploadedFile to a temp path and return the path."""
    suffix = Path(uploaded_file.name).suffix or ".apd"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_file.read())
    tmp.flush()
    tmp.close()
    return tmp.name


def build_fault_spec(cfg: dict, overrides: dict) -> FaultSpec:
    """Merge config defaults with user overrides into a :class:`FaultSpec`."""
    merged = {**cfg, **overrides}
    return FaultSpec(
        tag=merged["tag"],
        fault_type=FaultType(merged["fault_type"]),
        magnitude=float(merged["magnitude"]),
        start_time=float(merged["start_time"]),
        duration=float(merged["duration"]) if merged.get("duration") else None,
        profile=FaultProfile(merged.get("profile", "step")),
        ramp_duration=float(merged.get("ramp_duration", 60.0)),
        label=merged.get("label", ""),
    )


def run_simulation(
    apd_path: str | None,
    fault_spec: FaultSpec,
    monitored_tags: list[str],
    dt: float,
    t_end: float,
    fault_label: str,
) -> DataCollector:
    """Open the APD, run the simulation, collect data, and return the collector."""
    collector = DataCollector(fault_label=fault_label)

    apd_file = apd_path  # may be None → mock mode

    with APDInterface(apd_file) as apd:
        mode_str = "mock" if apd.mock_mode else "live APD"
        logger.info("Running %s simulation (mode=%s)", fault_label, mode_str)

        simulator = FaultSimulator(apd, [fault_spec] if fault_spec.fault_type != FaultType.NORMAL else [])
        apd.run()

        progress_bar = st.progress(0)
        status_text = st.empty()

        step_count = int((t_end / dt)) + 1
        for i, (t, row) in enumerate(
            simulator.step_generator(dt=dt, t_end=t_end, monitored_tags=monitored_tags)
        ):
            collector.record(t, row)
            pct = min(int(i / step_count * 100), 100)
            progress_bar.progress(pct)
            status_text.text(f"Simulation time: {t:.0f} s / {t_end:.0f} s")

        progress_bar.progress(100)
        status_text.text("Simulation complete ✓")
        apd.pause()

    return collector


# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="PET FDD — Fault Data Generator",
        page_icon="⚗️",
        layout="wide",
    )

    st.title("⚗️ PET Depolymerisation — Fault Data Generator")
    st.markdown(
        """
        Upload an **Aspen Plus Dynamics (.apd)** file, choose a fault scenario,
        and generate a labelled time-series dataset for fault detection & diagnosis
        (FDD) model training.

        > **Note:** If Aspen Plus Dynamics is not installed (or you are on a non-Windows
        > system) the app runs in **mock mode** using representative steady-state values
        > so you can explore the interface without a licence.
        """
    )

    config = load_config()
    sim_cfg = config.get("simulation", {})
    fault_catalog = config.get("faults", {})
    monitored_tags: list[str] = config.get("monitored_tags", [])

    # -----------------------------------------------------------------------
    # Sidebar — file upload & simulation parameters
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.header("1 · APD File")
        uploaded = st.file_uploader(
            "Upload .apd file",
            type=["apd"],
            help="Leave empty to run in mock mode with representative PET process values.",
        )

        st.header("2 · Simulation Parameters")
        dt = st.number_input(
            "Time step dt [s]",
            min_value=1.0,
            max_value=600.0,
            value=float(sim_cfg.get("dt", 10.0)),
            step=1.0,
        )
        t_end = st.number_input(
            "Simulation end time [s]",
            min_value=dt,
            max_value=86400.0,
            value=float(sim_cfg.get("t_end", 1200.0)),
            step=60.0,
        )

        st.header("3 · Fault Scenario")
        scenario_keys = list(fault_catalog.keys())
        scenario_labels = [fault_catalog[k]["label"] for k in scenario_keys]
        selected_idx = st.selectbox(
            "Preset fault",
            range(len(scenario_keys)),
            format_func=lambda i: scenario_labels[i],
        )
        selected_key = scenario_keys[selected_idx]
        selected_cfg = fault_catalog[selected_key]

        with st.expander("Advanced — override fault parameters"):
            ov_magnitude = st.number_input(
                "Magnitude",
                value=float(selected_cfg["magnitude"]),
                format="%.4f",
            )
            ov_start = st.number_input(
                "Fault start time [s]",
                min_value=0.0,
                max_value=t_end,
                value=float(selected_cfg["start_time"]),
                step=10.0,
            )
            ov_duration_raw = st.text_input(
                "Duration [s] (blank = until end)",
                value="" if selected_cfg.get("duration") is None else str(selected_cfg["duration"]),
            )
            ov_profile = st.selectbox(
                "Profile",
                options=[p.value for p in FaultProfile],
                index=[p.value for p in FaultProfile].index(selected_cfg.get("profile", "step")),
            )
            ov_ramp_dur = st.number_input(
                "Ramp / drift duration [s]",
                min_value=1.0,
                value=float(selected_cfg.get("ramp_duration", 60.0)),
                step=10.0,
            )

        run_btn = st.button("▶ Run Simulation", type="primary", use_container_width=True)

    # -----------------------------------------------------------------------
    # Main panel — results
    # -----------------------------------------------------------------------
    st.subheader("Simulation Results")

    if run_btn:
        overrides = {
            "magnitude": ov_magnitude,
            "start_time": ov_start,
            "duration": float(ov_duration_raw) if ov_duration_raw.strip() else None,
            "profile": ov_profile,
            "ramp_duration": ov_ramp_dur,
        }
        fault_spec = build_fault_spec(selected_cfg, overrides)
        fault_label = selected_cfg["label"]

        apd_path: str | None = None
        if uploaded is not None:
            apd_path = save_uploaded_apd(uploaded)

        try:
            with st.spinner("Running simulation …"):
                collector = run_simulation(
                    apd_path=apd_path,
                    fault_spec=fault_spec,
                    monitored_tags=monitored_tags,
                    dt=dt,
                    t_end=t_end,
                    fault_label=fault_label,
                )
        finally:
            if apd_path and Path(apd_path).exists():
                os.unlink(apd_path)

        st.success(f"Collected **{collector.row_count}** data points.")

        try:
            df = collector.to_dataframe()
            st.dataframe(df, use_container_width=True)

            # Interactive chart of the faulted variable
            tag = fault_spec.tag
            if tag in df.columns:
                st.line_chart(df.set_index("time")[[tag]], use_container_width=True)
        except ImportError:
            st.info("Install pandas to preview the data as a table.")

        csv_content = collector.to_csv()
        st.download_button(
            label="⬇ Download CSV",
            data=csv_content,
            file_name=f"pet_fdd_{selected_key}.csv",
            mime="text/csv",
        )
    else:
        st.info("Configure the fault scenario in the sidebar and click **▶ Run Simulation**.")

        # Show the monitored variable list as a reference
        with st.expander("Monitored variables"):
            for tag in monitored_tags:
                st.code(tag)


if __name__ == "__main__":
    main()
