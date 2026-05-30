#!/bin/bash
# Pokemon Vault Launcher
cd "$(dirname "$0")"

# Kill any existing server on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null

# Start server in background
python3 -m http.server 8000 &
SERVER_PID=$!

# Wait a moment then open browser
sleep 1
open http://localhost:8000/vault.html

echo "============================================"
echo "  Pokemon Vault is running"
echo "  http://localhost:8000/vault.html"
echo "  Close this window to stop the server"
echo "============================================"

# Keep running until window is closed
wait $SERVER_PID
