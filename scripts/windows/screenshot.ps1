param(
    [string]$Output = "screenshot.png",
    [string]$Port,
    [string]$Python = "python",
    [switch]$ListPorts,
    [switch]$ResetBeforeCapture
)

$ErrorActionPreference = "Stop"

function Invoke-PythonText {
    param(
        [string]$Code,
        [string[]]$Arguments = @()
    )

    $tmpPy = Join-Path $env:TEMP ("clawdmeter-screenshot-" + [guid]::NewGuid().ToString() + ".py")
    try {
        Set-Content -LiteralPath $tmpPy -Value $Code -Encoding UTF8
        & $Python $tmpPy @Arguments
    } finally {
        Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
    }
}

$portProbeCode = @'
import serial.tools.list_ports

ports = list(serial.tools.list_ports.comports())
for port in ports:
    print(f"{port.device}\t{port.description}")
'@

if ($ListPorts) {
    Invoke-PythonText -Code $portProbeCode
    exit $LASTEXITCODE
}

if (-not $Port) {
    $detectCode = @'
import serial.tools.list_ports

ports = list(serial.tools.list_ports.comports())
preferred = ("USB JTAG", "wchusbserial", "CH340", "CP210", "USB Serial", "Silicon Labs")

def score(port):
    hay = f"{port.device} {port.description} {port.hwid}".lower()
    for idx, token in enumerate(preferred):
        if token.lower() in hay:
            return idx
    return len(preferred) + 1

ports.sort(key=lambda p: (score(p), p.device))
if ports:
    print(ports[0].device)
'@

    $Port = (Invoke-PythonText -Code $detectCode | Select-Object -Last 1).Trim()
}

if (-not $Port) {
    throw "No serial port found. Run with -ListPorts to inspect available ports."
}

$outputPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Output))
$outputDir = Split-Path -Parent $outputPath
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

Write-Host "Taking screenshot from $Port..."

$captureCode = @'
import struct
import sys
import time
from pathlib import Path

import serial
from PIL import Image

port_path, output_path = sys.argv[1], sys.argv[2]
reset_before_capture = len(sys.argv) > 3 and sys.argv[3] == "1"

def read_line(port):
    return port.readline().decode("utf-8", errors="replace").strip()

port = serial.Serial()
port.port = port_path
port.baudrate = 115200
port.timeout = 10
port.dtr = False
port.rts = False
port.open()
if reset_before_capture:
    port.rts = True
    time.sleep(0.2)
    port.rts = False
    time.sleep(0.35)
port.reset_input_buffer()
port.reset_output_buffer()

if reset_before_capture:
    deadline = time.time() + 8.0
    while time.time() < deadline:
        line = read_line(port)
        if not line:
            continue
        if line == '{"ready":true}':
            break

port.reset_input_buffer()
port.write(b"screenshot\n")
port.flush()

width = height = raw_size = None
streamed = False
canvas = None
while True:
    line = read_line(port)
    if line.startswith("SCREENSHOT_START"):
        parts = line.split()
        width, height, raw_size = int(parts[1]), int(parts[2]), int(parts[3])
        break
    if line.startswith("SCREENSHOT_BEGIN"):
        parts = line.split()
        width, height, raw_size = int(parts[1]), int(parts[2]), int(parts[3])
        canvas = bytearray(raw_size)
        streamed = True
        break
    if line == "SCREENSHOT_UNSUPPORTED":
        print("Device reported screenshot unsupported (likely no PSRAM)", file=sys.stderr)
        sys.exit(2)
    if line == "SCREENSHOT_ERR":
        print("Device reported screenshot error", file=sys.stderr)
        sys.exit(1)
    if not line:
        print("Timed out waiting for SCREENSHOT_START", file=sys.stderr)
        sys.exit(1)

if not streamed:
    data = bytearray()
    while len(data) < raw_size:
        chunk = port.read(min(4096, raw_size - len(data)))
        if not chunk:
            print(f"Timeout: got {len(data)} of {raw_size} bytes", file=sys.stderr)
            sys.exit(1)
        data.extend(chunk)

    for _ in range(10):
        line = read_line(port)
        if line == "SCREENSHOT_END":
            break
else:
    received = 0
    deadline = time.time() + 20
    while True:
        line = read_line(port)
        if not line:
            if time.time() > deadline:
                print("Timed out waiting for screenshot tile data", file=sys.stderr)
                sys.exit(1)
            continue
        if line == "SCREENSHOT_END":
            break
        if line.startswith("SCREENSHOT_MISMATCH"):
            print(line, file=sys.stderr)
            continue
        if not line.startswith("SCREENSHOT_TILE"):
            continue

        parts = line.split()
        x, y, tile_w, tile_h, tile_bytes = map(int, parts[1:6])
        tile = bytearray()
        while len(tile) < tile_bytes:
            chunk = port.read(min(4096, tile_bytes - len(tile)))
            if not chunk:
                print(f"Timeout: got {len(tile)} of {tile_bytes} tile bytes", file=sys.stderr)
                sys.exit(1)
            tile.extend(chunk)

        for row in range(tile_h):
            src_start = row * tile_w * 2
            src_end = src_start + tile_w * 2
            dst_start = ((y + row) * width + x) * 2
            canvas[dst_start:dst_start + tile_w * 2] = tile[src_start:src_end]

        received += tile_bytes
        deadline = time.time() + 20

    if received != raw_size:
        print(f"Warning: received {received} of {raw_size} screenshot bytes", file=sys.stderr)
    data = canvas

port.close()

pixels = memoryview(data)
rgb = bytearray(width * height * 3)

for i in range(width * height):
    value = struct.unpack_from("<H", pixels, i * 2)[0]
    r = ((value >> 11) & 0x1F) * 255 // 31
    g = ((value >> 5) & 0x3F) * 255 // 63
    b = (value & 0x1F) * 255 // 31
    base = i * 3
    rgb[base] = r
    rgb[base + 1] = g
    rgb[base + 2] = b

image = Image.frombytes("RGB", (width, height), bytes(rgb))
output = Path(output_path)
image.save(output)

print(f"Captured {width}x{height} ({len(data)} bytes)")
print(f"Saved: {output}")
'@

Invoke-PythonText -Code $captureCode -Arguments @($Port, $outputPath, $(if ($ResetBeforeCapture) { "1" } else { "0" }))
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
