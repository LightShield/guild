#!/usr/bin/env bash
# Remote Ollama Setup — run this on the machine hosting Ollama
# to expose it on the LAN for development from another machine.
#
# Usage (on the Ollama host):
#   ./scripts/remote-ollama-setup.sh
#
# Then on the dev machine:
#   ./scripts/remote-ollama-setup.sh --client <ollama-host-ip>

set -euo pipefail

if [[ "${1:-}" == "--client" ]]; then
    # Client mode: configure Guild to point at remote Ollama
    HOST="${2:?Usage: $0 --client <ollama-host-ip>}"
    PORT="${3:-11434}"
    URL="http://${HOST}:${PORT}"

    echo "Testing connection to ${URL}..."
    if curl -sf "${URL}/api/tags" > /dev/null 2>&1; then
        echo "OK — Ollama reachable at ${URL}"
        curl -sf "${URL}/api/tags" | python3 -m json.tool 2>/dev/null || true
    else
        echo "FAILED — cannot reach Ollama at ${URL}"
        echo ""
        echo "Checklist:"
        echo "  1. Is Ollama running on ${HOST}?"
        echo "  2. Did you set OLLAMA_HOST=0.0.0.0 and restart Ollama?"
        echo "  3. Is port ${PORT} open? (Windows Firewall may block it)"
        exit 1
    fi

    echo ""
    echo "To configure Guild, run:"
    echo "  guild config --set provider.base_url=${URL}"
    echo ""
    echo "Or create/edit .guild/config.toml:"
    echo "  [provider]"
    echo "  base_url = \"${URL}\""
    exit 0
fi

# Server mode: configure Ollama to listen on all interfaces
echo "=== Remote Ollama Setup (Server) ==="
echo ""

# Detect OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    echo "Detected: Windows (git bash)"
    echo ""

    # Check if Ollama is installed
    if ! command -v ollama &> /dev/null; then
        echo "ERROR: ollama not found in PATH"
        exit 1
    fi

    echo "Step 1: Setting OLLAMA_HOST=0.0.0.0 (listen on all interfaces)"
    setx OLLAMA_HOST "0.0.0.0" 2>/dev/null || {
        echo "  Failed to set via setx. Set manually:"
        echo "    System Settings → Environment Variables → OLLAMA_HOST = 0.0.0.0"
    }
    export OLLAMA_HOST="0.0.0.0"

    echo ""
    echo "Step 2: Restart Ollama"
    echo "  Close the Ollama tray icon and relaunch it, or run:"
    echo "    taskkill //IM ollama.exe //F && ollama serve &"

    echo ""
    echo "Step 3: Verify"
    echo "  curl http://localhost:11434/api/tags"

    echo ""
    echo "Step 4: Find your IP"
    ipconfig 2>/dev/null | grep "IPv4" || echo "  Run: ipconfig | grep IPv4"

    echo ""
    echo "Step 5: Windows Firewall"
    echo "  If the dev machine can't connect, allow port 11434:"
    echo "    netsh advfirewall firewall add rule name=\"Ollama\" dir=in action=allow protocol=TCP localport=11434"

elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "Detected: Linux"
    echo ""
    echo "Step 1: Edit Ollama service to listen on all interfaces:"
    echo "  sudo systemctl edit ollama"
    echo "  Add: Environment=\"OLLAMA_HOST=0.0.0.0\""
    echo ""
    echo "Step 2: Restart:"
    echo "  sudo systemctl restart ollama"
    echo ""
    echo "Step 3: Find your IP:"
    hostname -I 2>/dev/null | awk '{print $1}' || ip addr show | grep "inet " | grep -v 127.0.0.1

elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Detected: macOS"
    echo ""
    echo "Step 1: Set environment variable:"
    echo "  launchctl setenv OLLAMA_HOST 0.0.0.0"
    echo ""
    echo "Step 2: Restart Ollama (quit from menu bar, relaunch)"
    echo ""
    echo "Step 3: Find your IP:"
    ipconfig getifaddr en0 2>/dev/null || echo "  Run: ipconfig getifaddr en0"
fi

echo ""
echo "=== Done ==="
echo "On the dev machine, run:"
echo "  ./scripts/remote-ollama-setup.sh --client <this-machine-ip>"
