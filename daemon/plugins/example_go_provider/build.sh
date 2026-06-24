#!/bin/bash
# build.sh — compile the Go example plugin
set -euo pipefail
cd "$(dirname "$0")"
go build -o ../example-provider .
echo "Built: example-provider"
