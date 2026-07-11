# Airport Queue Optimization Platform

An applied airport-operations prototype that combines **computer vision, queueing theory, simulation, and an interactive dashboard** to estimate congestion and support dynamic staffing decisions across passenger-processing zones.

The project models the passenger journey through check-in, bag drop, security, passport control, and boarding. It converts occupancy observations into operational queue metrics, forecasts short-term pressure, and recommends when service positions should be opened or closed.

> **Project status:** functional prototype developed with configurable airport scenarios and synthetic/demo data. It is intended as an interpretable decision-support system, not as a production deployment.

## Why this project

Airport congestion is not only a visualization problem. A useful operational system must distinguish between:

- how many passengers are currently visible in a zone;
- how quickly new passengers are arriving;
- how much service capacity is available;
- whether the queue is stable;
- and what staffing action is likely to reduce waiting time.

A central design decision in this project is to **avoid treating occupancy as an arrival rate**. Instead, arrivals are estimated from the balance between consecutive measurements:

```text
estimated arrivals = current occupancy - previous occupancy + estimated passengers served
```

This produces a more meaningful input for the queueing model and avoids systematically overstating demand.

## Core capabilities

- **Configurable airport topology** through JSON files: zones, connections, service rates, and staffing limits.
- **M/M/c queueing engine** using Erlang-C metrics for multi-server service systems.
- **Dynamic staffing recommendations** with bounded open/close actions for operational realism.
- **Short-horizon forecasts** for queue pressure at 5, 10, and 15 minutes.
- **Interactive Streamlit dashboard** with KPIs, zone-level status, saturation charts, recommendations, and an operational network map.
- **Continuous demand simulator** with multiple traffic profiles for testing low, medium, high, and peak-load conditions.
- **Scenario editor** for creating and comparing custom airport configurations without changing the queueing engine.
- **Computer-vision ingestion pipeline** based on YOLO person detection for converting video observations into occupancy measurements.
- **Weather-aware boarding indicators** that can adjust operational pressure and recommended boarding buffers.

## System architecture

```mermaid
flowchart LR
    A[Video or simulated demand] --> B[Occupancy measurements]
    B --> C[Temporal flow estimation]
    C --> D[M/M/c queue engine]
    E[Airport JSON configuration] --> D
    D --> F[Queue metrics and forecasts]
    F --> G[Staffing recommendations]
    F --> H[Streamlit dashboard]
    G --> H
```

## Queueing model

For each operational zone, the engine estimates and reports:

- passenger arrival rate (`lambda`);
- service rate per active server (`mu`);
- utilization (`rho`);
- expected queue length (`Lq`);
- expected waiting time (`Wq`);
- expected total time in the system (`W`);
- probability of an empty system (`P0`);
- queue stability;
- predicted queue pressure;
- recommended number of active service positions.

The current model represents a connected passenger flow rather than isolated queues, allowing upstream congestion to be interpreted in the context of the complete airport process.

## Dashboard

The dashboard provides:

- airport configuration selection;
- continuous demand simulation controls;
- live reprocessing when new measurements arrive;
- headline operational indicators;
- zone-by-zone queue metrics;
- congestion status and staffing recommendations;
- an interactive airport-process graph;
- configurable saturation thresholds;
- optional weather-related operational context;
- a visual editor for custom airport scenarios.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/javiergonzalvez07-star/Optimizacion-Inteligente-Colas-Aeropuertos.git
cd Optimizacion-Inteligente-Colas-Aeropuertos
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Launch the dashboard

```bash
python -m streamlit run dashboard/Principal.py
```

On Windows, the included helper scripts can also be used:

```powershell
.\run_dashboard.ps1
```

or

```bat
run_dashboard.bat
```

### 5. Run a scenario

From the dashboard:

1. Select an airport configuration.
2. Start the continuous simulator and choose a demand profile.
3. Allow at least two measurements to be generated.
4. Run the queue engine.
5. Open the operational dashboard to inspect congestion and recommendations.

## Main project structure

```text
.
├── airport_config.json        # Default airport topology and service configuration
├── assets/                    # Custom and alternative airport configurations
├── colas/                     # Queueing engine and continuous demand simulator
├── dashboard/                 # Streamlit application, adapters, components, and pages
├── outputs/                   # Generated occupancy readings and queue reports
├── requirements.txt           # Python dependencies
├── run_dashboard.bat          # Windows launcher
└── run_dashboard.ps1          # PowerShell launcher
```

## Technologies

- Python
- pandas and NumPy
- Streamlit
- Plotly
- NetworkX and PyVis
- OpenCV
- Ultralytics YOLO
- JSON-based configuration
- Queueing theory and Erlang-C modelling

## Engineering decisions

### Interpretability over black-box optimization

The system exposes the assumptions behind demand, service capacity, utilization, and staffing recommendations. The objective is to make operational decisions explainable rather than merely outputting a score.

### Configurable model instead of airport-specific hard-coding

Airport zones, connections, service rates, and staffing limits can be changed through configuration files. This keeps the analytical engine reusable across different terminal layouts and demand scenarios.

### Realistic operational guardrails

Recommended staffing changes are intentionally bounded to avoid implausible jumps between consecutive measurements.

## Limitations and next steps

Current limitations:

- the prototype primarily uses synthetic/demo scenarios;
- service-time assumptions require calibration with real operational data;
- computer-vision counts can be affected by occlusion, camera placement, and model confidence;
- the M/M/c assumptions simplify real passenger behavior and service variability;
- recommendations are decision support, not autonomous operational commands.

Planned extensions:

- calibrate service distributions with real observations;
- evaluate non-exponential service-time models;
- add historical scenario comparison and experiment tracking;
- validate forecasts against held-out operational sequences;
- package the pipeline for deployment on low-power edge hardware.

## Author

**Javier Gonzálvez Sempere**  
Double Degree student in Mathematical Engineering and Physics, interested in applied modelling, data science, simulation, AI, and technical systems.

- Portfolio: https://javiergonzalvez07-star.github.io/
- GitHub: https://github.com/javiergonzalvez07-star
