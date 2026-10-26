#!/bin/sh
set -eu
umask 077
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/probe-artifacts"
pids=''
cleanup() {
    for pid in $pids; do kill -TERM "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
Xvfb "$DISPLAY" -screen 0 1280x900x24 -nolisten tcp >"$HOME/probe-artifacts/display.log" 2>&1 &
pids="$pids $!"
attempt=0
until xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 20 ] || exit 2
    sleep 1
done
# VNC is container-loopback only; public access is authenticated by HTTPS nginx.
x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -forever -shared \
    -nopw -noxdamage -repeat -wait 50 -defer 20 -quiet \
    >"$HOME/probe-artifacts/vnc.log" 2>&1 &
pids="$pids $!"
websockify --web=/usr/share/novnc --heartbeat=30 \
    0.0.0.0:6080 127.0.0.1:5900 \
    >"$HOME/probe-artifacts/web.log" 2>&1 &
pids="$pids $!"
dbus-run-session -- /opt/wechat/wechat >"$HOME/probe-artifacts/client.log" 2>&1 &
client_pid=$!
pids="$pids $client_pid"
set +e
wait "$client_pid"
status=$?
set -e
exit "$status"
