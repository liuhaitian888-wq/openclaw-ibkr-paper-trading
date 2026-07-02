#!/bin/zsh
set -eu

cd "${0:A:h}"
export TRADING_API_HOST="192.168.64.1"
export TRADING_API_PORT="8787"
export TRADING_MODE="DRY_RUN"
export ALLOW_TWS_STAGING="false"
export ALLOW_PAPER_TRANSMIT="false"

exec .venv313/bin/python api_service.py
