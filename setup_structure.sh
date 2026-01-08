#!/bin/bash
# UBenchAI-Framework Directory Structure Setup

# Create main source directories
mkdir -p src/ubenchai/{servers,clients,monitors,logs,interface,core,utils}
mkdir -p src/ubenchai/interface/{cli,web}

# Create supporting directories  
mkdir -p config
mkdir -p recipes/{servers,clients,monitors,benchmarks}
mkdir -p tests/{unit,integration}
mkdir -p docs/{design,api,guides}
mkdir -p scripts
mkdir -p templates/{reports,dashboards}
mkdir -p results
mkdir -p examples

# Create __init__.py files for Python packages
touch src/ubenchai/__init__.py
touch src/ubenchai/servers/__init__.py
touch src/ubenchai/clients/__init__.py
touch src/ubenchai/monitors/__init__.py
touch src/ubenchai/logs/__init__.py
touch src/ubenchai/interface/__init__.py
touch src/ubenchai/interface/cli/__init__.py
touch src/ubenchai/interface/web/__init__.py
touch src/ubenchai/core/__init__.py
touch src/ubenchai/utils/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/integration/__init__.py

echo "✅ Directory structure created successfully!"
