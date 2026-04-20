#!/bin/bash
# Rotate the DSI display and launch Chromium in kiosk mode.
# Cage runs this as its single application.

wlr-randr --output DSI-2 --transform 270

exec chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --ozone-platform=wayland \
    --touch-events=enabled \
    --enable-features=TouchpadOverscrollHistoryNavigation \
    http://localhost:8080
