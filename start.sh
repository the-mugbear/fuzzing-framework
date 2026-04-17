#!/usr/bin/env bash
# ============================================================================
# Protocol Fuzzer — Unified Startup Script
# ============================================================================
# Single entry point for all deployment modes. Automatically detects Docker
# vs Podman, builds containers, and launches services.
#
# Usage:
#   ./start.sh                    # Interactive menu
#   ./start.sh docker             # Docker Compose (build + up)
#   ./start.sh podman             # Podman Compose (build + up)
#   ./start.sh local              # Local Python processes (no containers)
#   ./start.sh status             # Check running services
#   ./start.sh stop               # Stop all services
#   ./start.sh logs [service]     # Tail logs (core, target-manager, probe)
#
# Environment variables:
#   FUZZER_CORE_PORT=8000         Core API port
#   FUZZER_TM_PORT=8001           Target Manager API port
#   FUZZER_TARGET_PORT=9999       Default target port (local mode only)
# ============================================================================

set -euo pipefail

# ---- Colors ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ---- Configuration ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CORE_PORT="${FUZZER_CORE_PORT:-8000}"
TM_PORT="${FUZZER_TM_PORT:-8001}"
TARGET_PORT="${FUZZER_TARGET_PORT:-9999}"
PID_DIR="$SCRIPT_DIR/.pids"

# ---- Helpers ----
info()  { echo -e "${BLUE}▸${RESET} $*"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}!${RESET} $*"; }
err()   { echo -e "${RED}✗${RESET} $*" >&2; }

banner() {
  echo -e "${BOLD}${CYAN}"
  echo "  ╔════════════════════════════════════════════════╗"
  echo "  ║        Protocol Fuzzer Framework               ║"
  echo "  ╚════════════════════════════════════════════════╝"
  echo -e "${RESET}"
}

wait_for_port() {
  local port=$1 name=$2 timeout=${3:-30}
  local elapsed=0
  while ! (echo >/dev/tcp/localhost/"$port") 2>/dev/null; do
    sleep 1
    elapsed=$((elapsed + 1))
    if [ "$elapsed" -ge "$timeout" ]; then
      err "$name did not start within ${timeout}s on port $port"
      return 1
    fi
  done
  ok "$name is ready on port $port"
}

# ---- Detect container runtime ----
detect_runtime() {
  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    echo "docker"
  elif command -v podman &>/dev/null; then
    echo "podman"
  else
    echo "none"
  fi
}

compose_cmd() {
  local runtime=$1
  if [ "$runtime" = "docker" ]; then
    if docker compose version &>/dev/null 2>&1; then
      echo "docker compose"
    elif command -v docker-compose &>/dev/null; then
      echo "docker-compose"
    else
      err "docker compose plugin not found"
      exit 1
    fi
  elif [ "$runtime" = "podman" ]; then
    if command -v podman-compose &>/dev/null; then
      echo "podman-compose"
    elif podman compose version &>/dev/null 2>&1; then
      echo "podman compose"
    else
      err "podman-compose not found. Install with: pip install podman-compose"
      exit 1
    fi
  fi
}

# ---- Container mode (Docker/Podman) ----
start_containers() {
  local runtime=$1
  local compose
  compose=$(compose_cmd "$runtime")
  
  info "Using ${BOLD}$runtime${RESET} ($compose)"

  info "Building containers..."
  $compose build

  info "Starting services..."
  $compose up -d

  echo ""
  info "Waiting for services..."
  wait_for_port "$CORE_PORT"     "Core API"        30
  wait_for_port "$TM_PORT"       "Target Manager"  20

  echo ""
  echo -e "${BOLD}Services running:${RESET}"
  echo -e "  ${GREEN}●${RESET} Core API + Web UI    ${CYAN}http://localhost:${CORE_PORT}/ui${RESET}"
  echo -e "  ${GREEN}●${RESET} Core REST API        ${CYAN}http://localhost:${CORE_PORT}/api/system/health${RESET}"
  echo -e "  ${GREEN}●${RESET} Target Manager       ${CYAN}http://localhost:${TM_PORT}/api/health${RESET}"
  echo ""
  echo -e "${DIM}Start a target server from the UI: Targets tab → click Start${RESET}"
  echo -e "${DIM}View logs:  ./start.sh logs${RESET}"
  echo -e "${DIM}Stop all:   ./start.sh stop${RESET}"
}

# ---- Local mode (no containers) ----
start_local() {
  mkdir -p "$PID_DIR"

  info "Installing dependencies..."
  pip install -q -r requirements.txt

  # Check if SPA is built
  if [ ! -d "core/ui/spa/dist" ]; then
    info "Building Web UI..."
    (cd core/ui/spa && npm install && npm run build)
  fi

  info "Starting Core API on port $CORE_PORT..."
  FUZZER_API_PORT="$CORE_PORT" python -m core.api.server &
  echo $! > "$PID_DIR/core.pid"

  info "Starting Target Manager on port $TM_PORT..."
  python -c "
import uvicorn
from target_manager.server import app
uvicorn.run(app, host='0.0.0.0', port=$TM_PORT)
" &
  echo $! > "$PID_DIR/target_manager.pid"

  echo ""
  info "Waiting for services..."
  wait_for_port "$CORE_PORT"  "Core API"        15
  wait_for_port "$TM_PORT"    "Target Manager"  10

  echo ""
  echo -e "${BOLD}Services running (local mode):${RESET}"
  echo -e "  ${GREEN}●${RESET} Core API + Web UI    ${CYAN}http://localhost:${CORE_PORT}/ui${RESET}"
  echo -e "  ${GREEN}●${RESET} Target Manager       ${CYAN}http://localhost:${TM_PORT}/api/health${RESET}"
  echo ""
  echo -e "${DIM}Target servers are managed via the UI or Target Manager API.${RESET}"
  echo -e "${DIM}Stop all:   ./start.sh stop${RESET}"
}

# ---- Stop ----
stop_all() {
  local stopped=0

  # Stop containers
  local runtime
  runtime=$(detect_runtime)
  if [ "$runtime" != "none" ]; then
    local compose
    compose=$(compose_cmd "$runtime" 2>/dev/null || true)
    if [ -n "$compose" ]; then
      info "Stopping containers..."
      $compose down 2>/dev/null && stopped=1 || true
    fi
  fi

  # Stop local processes
  if [ -d "$PID_DIR" ]; then
    for pidfile in "$PID_DIR"/*.pid; do
      [ -f "$pidfile" ] || continue
      local pid
      pid=$(cat "$pidfile")
      if kill -0 "$pid" 2>/dev/null; then
        info "Stopping PID $pid ($(basename "$pidfile" .pid))..."
        kill "$pid" 2>/dev/null || true
        stopped=1
      fi
      rm -f "$pidfile"
    done
    rmdir "$PID_DIR" 2>/dev/null || true
  fi

  if [ "$stopped" -eq 1 ]; then
    ok "All services stopped"
  else
    warn "No running services found"
  fi
}

# ---- Status ----
show_status() {
  echo -e "${BOLD}Service Status${RESET}"
  echo ""

  # Check Core API
  if curl -sf "http://localhost:$CORE_PORT/api/system/health" >/dev/null 2>&1; then
    local health
    health=$(curl -sf "http://localhost:$CORE_PORT/api/system/health")
    local sessions
    sessions=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'active={d.get(\"active_sessions\",0)} total={d.get(\"total_sessions\",0)}')" 2>/dev/null || echo "")
    echo -e "  ${GREEN}●${RESET} Core API        :$CORE_PORT  $sessions"
  else
    echo -e "  ${RED}●${RESET} Core API        :$CORE_PORT  ${DIM}not running${RESET}"
  fi

  # Check Target Manager
  if curl -sf "http://localhost:$TM_PORT/api/health" >/dev/null 2>&1; then
    local tm_health
    tm_health=$(curl -sf "http://localhost:$TM_PORT/api/health")
    local tm_info
    tm_info=$(echo "$tm_health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'servers={d.get(\"available_servers\",0)} running={d.get(\"running_targets\",0)}')" 2>/dev/null || echo "")
    echo -e "  ${GREEN}●${RESET} Target Manager  :$TM_PORT  $tm_info"
  else
    echo -e "  ${RED}●${RESET} Target Manager  :$TM_PORT  ${DIM}not running${RESET}"
  fi

  # Check running targets
  if curl -sf "http://localhost:$TM_PORT/api/targets" >/dev/null 2>&1; then
    local targets
    targets=$(curl -sf "http://localhost:$TM_PORT/api/targets")
    local count
    count=$(echo "$targets" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    if [ "$count" -gt 0 ]; then
      echo ""
      echo -e "  ${BOLD}Running Targets:${RESET}"
      echo "$targets" | python3 -c "
import sys, json
for t in json.load(sys.stdin):
    health = '●' if t['health'] == 'healthy' else '○'
    print(f\"    {health} {t['name']:20s} :{t['port']}  {t['transport']}  ({','.join(t['compatible_plugins']) or 'any'})\")
" 2>/dev/null || true
    fi
  fi
  echo ""
}

# ---- Logs ----
show_logs() {
  local service="${1:-}"
  local runtime
  runtime=$(detect_runtime)

  if [ "$runtime" = "none" ]; then
    warn "No container runtime found. For local mode, check terminal output."
    return
  fi

  local compose
  compose=$(compose_cmd "$runtime")

  if [ -n "$service" ]; then
    $compose logs -f "$service"
  else
    $compose logs -f
  fi
}

# ---- Interactive menu ----
interactive_menu() {
  banner

  local runtime
  runtime=$(detect_runtime)

  echo -e "${BOLD}How would you like to run the fuzzer?${RESET}"
  echo ""

  if [ "$runtime" = "docker" ]; then
    echo -e "  ${GREEN}1${RESET})  Docker Compose       ${DIM}(detected)${RESET}"
  else
    echo -e "  ${DIM}1)  Docker Compose       (not detected)${RESET}"
  fi

  if [ "$runtime" = "podman" ] || command -v podman &>/dev/null; then
    echo -e "  ${GREEN}2${RESET})  Podman Compose       ${DIM}(detected)${RESET}"
  else
    echo -e "  ${DIM}2)  Podman Compose       (not detected)${RESET}"
  fi

  echo -e "  ${GREEN}3${RESET})  Local Python          ${DIM}(no containers)${RESET}"
  echo -e "  ${GREEN}4${RESET})  Check status"
  echo -e "  ${GREEN}5${RESET})  Stop all services"
  echo ""

  read -rp "Choose [1-5]: " choice
  echo ""

  case "$choice" in
    1) start_containers "docker" ;;
    2) start_containers "podman" ;;
    3) start_local ;;
    4) show_status ;;
    5) stop_all ;;
    *) err "Invalid choice"; exit 1 ;;
  esac
}

# ---- Main dispatch ----
case "${1:-}" in
  docker)   start_containers "docker" ;;
  podman)   start_containers "podman" ;;
  local)    start_local ;;
  status)   show_status ;;
  stop)     stop_all ;;
  logs)     show_logs "${2:-}" ;;
  help|-h|--help)
    banner
    echo "Usage: ./start.sh [command]"
    echo ""
    echo "Commands:"
    echo "  docker     Build and start with Docker Compose"
    echo "  podman     Build and start with Podman Compose"
    echo "  local      Start services locally (no containers)"
    echo "  status     Show status of all services"
    echo "  stop       Stop all services"
    echo "  logs       Tail service logs (optionally: logs core, logs target-manager)"
    echo "  help       Show this help"
    echo ""
    echo "Run without arguments for an interactive menu."
    ;;
  "")       interactive_menu ;;
  *)        err "Unknown command: $1. Run ./start.sh help"; exit 1 ;;
esac
