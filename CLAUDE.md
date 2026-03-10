# ZyphraExps — Project Instructions

## Stack

- **Backend**: Python 3.12, BrainFlow, WebSocket (websockets), MNE, NumPy
- **Frontend**: TanStack Start (React 19 + Vite), Tailwind CSS 4, shadcn/ui, pnpm
- **Hardware**: Muse 2 EEG headband (BrainFlow board_id=38)
- **ML**: ZUNA v0.1.1 (EEG superresolution), PyTorch, BrainFlow MLModel

## Running

```bash
# Backend (from project root)
python -m backend.main --synthetic   # or --mac "XX:XX:XX:XX:XX:XX"

# Frontend
cd frontend && pnpm dev

# Tests
python -m pytest tests/ -v
```

## Key Conventions

- Detector pipeline stages live in `backend/pipeline/stages/detectors.py`
- Recordings save to `recordings/<label>/` as `.npz` + `.fif`
- Experiment tracking via `scripts/experiment.py` → `experiments/`
- Research docs go to `docs/research/YYYY-MM-DD-<topic>.md`
- All EEG values in backend are µV; MNE .fif files store V (multiply by 1e-6)

## Hardware Safety

- **NEVER kill the backend while Muse is connected** — forces BLE disconnect, requires power cycle
- Always gracefully disconnect or ask user to power off Muse first

## Shadow Learning

This project uses shadow learning. Learned patterns and entity context are stored in the auto memory directory.

Before work that involves judgment (reviews, architecture, writing):
- Read `patterns/*.md` files in the memory directory for domain-specific rules
- Read `entities/*.md` files for context about people, services, or systems

When the user corrects you, note the correction explicitly — it will be extracted later.
