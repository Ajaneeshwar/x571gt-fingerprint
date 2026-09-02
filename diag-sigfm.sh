#!/bin/bash
# Standalone enroll/verify test against the patched build (no fprintd needed).
# Run as root. Build first: clone the sigfm branch as ./libfprint-sigfm,
# run apply-sigfm-changes.py, then: meson setup build -Ddrivers=elanspi \
#   -Ddoc=false -Dintrospection=false -Dgtk-examples=false && ninja -C build
D="$(cd "$(dirname "$0")" && pwd)"
B=$D/libfprint-sigfm/build/examples
[ -x "$B/enroll" ] || { echo "build libfprint-sigfm first (see comment above)"; exit 1; }
cd "$D"
echo ">>> ENROLL (7 presses): PRESS and hold ~1s, lift fully, repeat when it waits again."
printf '5\n' | G_MESSAGES_DEBUG=all timeout 120 "$B/enroll" > "$D/sigfm-enroll.log" 2>&1
echo "    enroll done (exit $?)"
echo ""
echo ">>> Finger OFF the sensor..."
sleep 4
echo ">>> VERIFY: one press, same finger."
printf '5\nn\n' | G_MESSAGES_DEBUG=all timeout 45 "$B/verify" > "$D/sigfm-verify.log" 2>&1
echo "=== enroll stages ==="
grep -hiE "stage.*passed|enroll progress" "$D/sigfm-enroll.log" | tail -8
echo "=== verify result ==="
grep -hiE "sigfm score|match report|MATCH" "$D/sigfm-verify.log" | tail -8
