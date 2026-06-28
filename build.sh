#!/bin/bash
set -e

echo "=== Building CR Coach Bot ==="

echo ">> Installing Python dependencies"
pip install -r requirements.txt

echo ">> Building frontend"
cd webapp
npm install
npm run build
cd ..

echo ">> Build complete"
