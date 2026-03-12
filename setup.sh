#!/usr/bin/env bash
set -euo pipefail

# ZyphraExps quick setup script
# Installs backend + frontend dependencies on a fresh machine.
# Prerequisites: Python 3.12+, Node 22+, pnpm

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== ZyphraExps Setup ==="

# Backend
echo ""
echo "--- Installing Python dependencies ---"
pip install -r backend/requirements.txt
pip install brainflow
echo "Backend ready."

# Frontend
echo ""
echo "--- Installing frontend dependencies ---"
cd frontend
pnpm install
cd ..
echo "Frontend ready."

echo ""
echo "=== Setup complete ==="
echo ""
echo "To run:"
echo "  Terminal 1:  python -m backend.main --synthetic"
echo "  Terminal 2:  cd frontend && pnpm dev"
echo ""
echo "Then open http://localhost:3000 (dashboard) or http://localhost:3000/demo (EUTERPE demo)"
echo ""
echo "For real Muse 2 hardware:"
echo "  sudo systemctl start bluetooth"
echo "  bluetoothctl scan on    # find your Muse MAC"
echo "  python -m backend.main --mac 'XX:XX:XX:XX:XX:XX'"
