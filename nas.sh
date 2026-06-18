#!/bin/bash
# Run a command on the Synology NAS via SSH (prepends the PATH docker needs).
# NAS project dir: /volume2/Docker/AlpacaHedgeFund  (mounted as /app in container alpaca-hedge-fund)
#
# Examples:
#   ./nas.sh "docker compose -f /volume2/Docker/AlpacaHedgeFund/docker-compose.yml ps"
#   ./nas.sh "docker exec alpaca-hedge-fund sh -c 'cd /app && python3 run_scoring.py'"
ssh -i ~/.ssh/claude_nas -o StrictHostKeyChecking=no admin@10.0.1.6 "export PATH=/usr/local/bin:/usr/bin:/bin && $*"
