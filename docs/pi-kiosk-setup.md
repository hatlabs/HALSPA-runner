# Raspberry Pi Kiosk Setup

How to set up a Raspberry Pi as a HALSPA test runner kiosk with a touchscreen.

Starting point: Raspberry Pi OS Lite (Bookworm), no desktop installed, touchscreen connected via DSI.

## 1. Install packages

```bash
sudo apt update
sudo apt install -y cage chromium-browser wlr-randr
```

- **cage**: minimal Wayland kiosk compositor — runs a single app fullscreen
- **chromium-browser**: displays the HALSPA Runner web UI
- **wlr-randr**: Wayland output configuration (display rotation)

## 2. Auto-login on TTY1

Create a systemd override for getty on TTY1:

```bash
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin mairas --noclear %I \$TERM
EOF
```

Replace `mairas` with the target username.

## 3. Auto-start cage on login

Add to `~/.config/fish/config.fish` (for fish shell):

```fish
# Auto-start cage kiosk on TTY1
if test (tty) = /dev/tty1
    set -x WLR_LIBINPUT_NO_DEVICES 1
    exec cage -s -- ~/src/HALSPA/HALSPA-runner/deploy/kiosk-start.sh
end
```

For bash, add the equivalent to `~/.bash_profile`:

```bash
if [ "$(tty)" = "/dev/tty1" ]; then
    export WLR_LIBINPUT_NO_DEVICES=1
    exec cage -s -- ~/src/HALSPA/HALSPA-runner/deploy/kiosk-start.sh
fi
```

The `kiosk-start.sh` wrapper (`deploy/kiosk-start.sh`) handles display rotation via `wlr-randr` and launches Chromium in kiosk mode. Edit the `--transform` value there if rotation needs adjusting.

Key flags:
- `cage -s`: disable VT switching (locks kiosk to single app)
- `--ozone-platform=wayland`: run Chromium natively on Wayland
- `--touch-events=enabled`: enable touch input
- `--kiosk`: fullscreen, no browser chrome

### Display rotation

The DSI touchscreen panel is 720x1280 (portrait native). Physical mounting determines which `wlr-randr --transform` value is needed in `deploy/kiosk-start.sh`:

| Physical orientation | Transform value |
|---------------------|----------------|
| Portrait (no rotation needed) | `normal` |
| Landscape (rotated 90° CW) | `90` |
| Portrait (upside down) | `180` |
| Landscape (rotated 90° CCW) | `270` |

Note: `display_lcd_rotate` and DT overlay `rotation` parameters only affect the console framebuffer, not Wayland. Use `wlr-randr` for cage/Chromium rotation.

## 4. Enable user lingering

Keeps systemd user services running even without an active login session:

```bash
sudo loginctl enable-linger mairas
```

## 5. Deploy HALSPA Runner

From the HALSPA-runner repo on the Pi:

```bash
./run deploy
```

This installs:
- systemd user service for the FastAPI backend (port 8080)
- Chromium kiosk autostart desktop entry (redundant with cage setup above, harmless)

## 6. Reboot

```bash
sudo reboot
```

On boot: TTY1 auto-login → fish launches cage → `kiosk-start.sh` rotates display and launches Chromium → Chromium connects to backend at localhost:8080.

## Troubleshooting

**Check backend status:**
```bash
systemctl --user status halspa-runner.service
journalctl --user -u halspa-runner.service -f
```

**Check if backend is responding:**
```bash
curl http://localhost:8080/api/status
```

**Check display transform:**
```bash
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 wlr-randr
```

**Touch not working:** Verify input devices:
```bash
sudo libinput list-devices
```

**Restart kiosk without reboot:** SSH in, then:
```bash
sudo systemctl restart getty@tty1.service
```
