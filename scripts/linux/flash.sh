#!/bin/bash
# Build and flash Clawdmeter firmware on Linux.
# Usage:
#   ./scripts/linux/flash.sh <board>              # default port /dev/ttyACM0
#   ./scripts/linux/flash.sh <board> /dev/ttyACM1 # explicit USB serial port
#
# <board> is the PlatformIO env name, e.g. waveshare_amoled_216 or waveshare_amoled_18.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BOARD="$1"
PORT="${2:-/dev/ttyACM0}"

if [ -z "$BOARD" ]; then
    echo "Error: board env name is required."
    echo "Usage: $0 <board> [port]"
    echo "Available boards:"
    grep -E '^\[env:' "$REPO_ROOT/firmware/platformio.ini" | sed 's/\[env:/  /;s/\]//'
    exit 1
fi

echo "=== Flashing Clawdmeter ==="
echo "Board: $BOARD"
echo "Port:  $PORT"
echo ""

cd "$REPO_ROOT/firmware"
~/.platformio/penv/bin/pio run -e "$BOARD" -t upload --upload-port "$PORT"

echo ""
echo "=== Done! ==="
