# PET_FDD

**Fault Detection & Diagnosis (FDD) framework for PET depolymerisation processes**

Data is acquired from **Aspen Plus Dynamics (APD)** via the Python–COM interface.
A Streamlit web app lets you upload an APD file, choose a fault scenario, run the
dynamic simulation, and download a labelled time-series dataset for FDD model training.

---

## Repository structure

```
PET_FDD/
├── app.py                     # Streamlit web app
├── requirements.txt           # Python dependencies
├── apd/
│   ├── __init__.py
│   ├── interface.py           # Python-APD COM interface (+ mock for non-Windows)
│   ├── fault_simulator.py     # Fault injection (sensor / actuator / process faults)
│   └── data_collector.py      # Time-series data collection & CSV/DataFrame export
├── config/
│   └── fault_config.yaml      # Default fault scenarios and simulation parameters
└── tests/
    ├── test_interface.py
    ├── test_fault_simulator.py
    └── test_data_collector.py
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> **Windows + Aspen Plus Dynamics:** additionally install pywin32:
> ```bash
> pip install pywin32
> ```

### 2. Run the Streamlit app

```bash
streamlit run app.py
```

Open the browser URL shown in the terminal (usually `http://localhost:8501`).

### 3. Using the app

1. **(Optional) Upload an `.apd` file** in the sidebar.  
   If no file is uploaded the app runs in **mock mode** using representative
   steady-state values for a PET depolymerisation process — useful for
   exploring the interface without a licence.

2. **Set simulation parameters** — time step and end time.

3. **Select a fault scenario** from the preset catalogue (or expand
   *Advanced* to override individual parameters).

4. Click **▶ Run Simulation**.

5. Inspect the data table and time-series chart, then **⬇ Download CSV**.

---

## Fault scenarios

| Scenario | Variable | Type | Magnitude |
|---|---|---|---|
| Normal operation | — | — | — |
| Reactor temperature high | `REACTOR/T` | Process step | +10 °C |
| Reactor temperature low | `REACTOR/T` | Process step | −10 °C |
| Feed flow increase | `FEED/FmR` | Process step | +20 kg/h |
| Feed flow decrease | `FEED/FmR` | Process step | −20 kg/h |
| Cooling-water flow loss | `CW_IN/FmR` | Process ramp | −50 kg/h |
| Catalyst flow low | `CAT/FmR` | Process step | −0.5 kg/h |
| Temperature sensor bias | `REACTOR/T` | Sensor bias | +5 °C |
| Temperature sensor drift | `REACTOR/T` | Sensor drift | up to +8 °C |
| Temperature sensor failure | `REACTOR/T` | Sensor failure | stuck at 999 |
| Reactor pressure high | `REACTOR/P` | Process ramp | +0.2 bar |

Custom faults can be added to `config/fault_config.yaml`.

---

## Programmatic API

```python
from apd import APDInterface, FaultSimulator, FaultSpec, FaultType, DataCollector

specs = [
    FaultSpec(
        tag="\\Data\\Blocks\\REACTOR\\Variables\\T\\",
        fault_type=FaultType.PROCESS_STEP,
        magnitude=+10.0,
        start_time=300.0,
    )
]

collector = DataCollector(fault_label="reactor_temp_high")

with APDInterface("C:/Simulations/pet.apd") as apd:
    sim = FaultSimulator(apd, specs)
    apd.run()
    for t, row in sim.step_generator(dt=10.0, t_end=1200.0):
        collector.record(t, row)
    apd.pause()

collector.to_csv("fault_data.csv")
df = collector.to_dataframe()
```

---

## Running tests

```bash
pytest tests/ -v
```

Tests run entirely in **mock mode** — no Aspen Plus installation required.

---

## Connecting to a live Aspen Plus Dynamics session

The `APDInterface` uses `win32com.client.Dispatch("Apwn.Document")` to open
`.apd` files via COM automation.  This requires:

* **Windows** operating system
* **Aspen Plus Dynamics** installed and licenced
* **pywin32** (`pip install pywin32`)

Variable paths follow the Aspen tree structure, e.g.
`\\Data\\Blocks\\REACTOR\\Variables\\T\\`.  Use the Aspen variable browser to
look up the exact path for your model.
