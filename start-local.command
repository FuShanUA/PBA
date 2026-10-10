#!/bin/zsh
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

ROOT=${0:A:h}
cd "$ROOT" || exit 1

healthy() {
  curl -fsS --max-time 2 "http://127.0.0.1:$1/api/status" >/dev/null 2>&1
}

listener_pid() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -n 1
}

stop_known_listener() {
  local port=$1
  local pid
  local command

  pid=$(listener_pid "$port")
  [[ -z "$pid" ]] && return 1

  command=$(ps -p "$pid" -o command= 2>/dev/null || true)
  if [[ "$command" != *"-m http.server $port"* && "$command" != *"$ROOT/server.py"*"--port $port"* ]]; then
    return 1
  fi

  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    [[ -z $(listener_pid "$port") ]] && return 0
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
  return 0
}

PORT=8765
if healthy "$PORT"; then
  URL="http://127.0.0.1:$PORT/"
  echo "Local archive is already running: $URL"
  open "$URL"
  exit 0
fi

if ! stop_known_listener "$PORT"; then
  if [[ -n $(listener_pid "$PORT") ]]; then
    echo "Port $PORT is used by another process. Trying a backup port."
    PORT=0
    for candidate in {8766..8775}; do
      if [[ -z $(listener_pid "$candidate") ]]; then
        PORT=$candidate
        break
      fi
    done
    if [[ "$PORT" == 0 ]]; then
      echo "No local port is available from 8766 to 8775."
      exit 1
    fi
  fi
fi

URL="http://127.0.0.1:$PORT/"
echo "Local archive started: $URL"

nohup python3 "$ROOT/server.py" --host 127.0.0.1 --port "$PORT" >/tmp/palantir-archive.log 2>&1 &
SERVER_PID=$!
disown "$SERVER_PID"

for _ in {1..50}; do
  if healthy "$PORT"; then
    open "$URL" 2>/dev/null || true
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Local archive failed to start."
    exit 1
  fi
  sleep 0.1
done

if ! healthy "$PORT"; then
  echo "Local archive did not become ready."
  kill "$SERVER_PID" 2>/dev/null || true
  exit 1
fi

exit 0
