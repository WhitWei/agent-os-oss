#!/usr/bin/env bash
set -e

# Define paths
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${ROOT_DIR}/agentos-ui"
DASHBOARD_DIR="${ROOT_DIR}/src/agentos/static/dashboard"

echo "Building frontend..."
cd "${UI_DIR}"

echo "Installing dependencies..."
npm install

echo "Running Next.js build..."
npm run build

echo "Clearing backend static directory..."
rm -rf "${DASHBOARD_DIR}"
mkdir -p "${DASHBOARD_DIR}"

echo "Moving build artifacts to backend..."
cp -R out/* "${DASHBOARD_DIR}/"

echo "Build and integration complete!"
