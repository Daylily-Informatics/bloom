#!/bin/bash
# BLOOM Analytics - Metabase Standalone Runner
# This script downloads and runs Metabase without Docker

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METABASE_VERSION="${METABASE_VERSION:-v0.48.6}"
METABASE_JAR="$SCRIPT_DIR/metabase.jar"
METABASE_DATA_DIR="$SCRIPT_DIR/metabase-data"
METABASE_PORT="${METABASE_PORT:-3000}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== BLOOM Analytics - Metabase Runner ===${NC}"

# Check for Java
if ! command -v java &> /dev/null; then
    echo -e "${RED}Error: Java is not installed.${NC}"
    echo "Please install Java 11 or higher:"
    echo "  macOS: brew install openjdk@11"
    echo "  Ubuntu: sudo apt install openjdk-11-jre"
    exit 1
fi

JAVA_VERSION=$(java -version 2>&1 | head -n 1 | cut -d'"' -f2 | cut -d'.' -f1)
if [ "$JAVA_VERSION" -lt 11 ]; then
    echo -e "${RED}Error: Java 11 or higher is required (found version $JAVA_VERSION)${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Java version: $(java -version 2>&1 | head -n 1)${NC}"

# Download Metabase if not present
if [ ! -f "$METABASE_JAR" ]; then
    echo -e "${YELLOW}Downloading Metabase $METABASE_VERSION...${NC}"
    DOWNLOAD_URL="https://downloads.metabase.com/$METABASE_VERSION/metabase.jar"
    
    if command -v curl &> /dev/null; then
        curl -L -o "$METABASE_JAR" "$DOWNLOAD_URL"
    elif command -v wget &> /dev/null; then
        wget -O "$METABASE_JAR" "$DOWNLOAD_URL"
    else
        echo -e "${RED}Error: Neither curl nor wget found. Please install one.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Metabase downloaded${NC}"
fi

# Create data directory
mkdir -p "$METABASE_DATA_DIR"

# Set environment variables
export MB_DB_TYPE=h2
export MB_DB_FILE="$METABASE_DATA_DIR/metabase.db"
export MB_JETTY_PORT="$METABASE_PORT"
export MB_SITE_NAME="BLOOM LIMS Analytics"
export MB_ENABLE_EMBEDDING=true

# Note: Configure Metabase via environment variables before running this script.
# See analytics/README.md for configuration details.

echo -e "${GREEN}Starting Metabase on port $METABASE_PORT...${NC}"
echo -e "${YELLOW}First startup may take 1-2 minutes to initialize.${NC}"
echo -e "${YELLOW}Access Metabase at: http://localhost:$METABASE_PORT${NC}"
echo ""
echo "Press Ctrl+C to stop Metabase"
echo ""

# Run Metabase
java -Xmx2g -jar "$METABASE_JAR"

