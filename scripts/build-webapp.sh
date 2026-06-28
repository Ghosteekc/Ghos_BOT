#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../webapp"
npm install
npm run build
echo "Built to webapp/dist/"
