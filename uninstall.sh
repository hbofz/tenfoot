#!/bin/sh
# Undoes install.sh. Leaves ~/.config/tenfoot (your links and settings) and installed packages alone.
set -u
systemctl --user disable --now tenfoot tenfoot-spotify tenfoot-airplay 2>/dev/null
rm -f "$HOME/.config/systemd/user/tenfoot.service" "$HOME/.config/systemd/user/tenfoot-spotify.service" "$HOME/.config/systemd/user/tenfoot-airplay.service"
systemctl --user daemon-reload
sed -i '/^# tenfoot kiosk/,/^fi$/d' "$HOME/.profile"
sudo rm -f /etc/chromium/policies/managed/tenfoot.json /etc/modules-load.d/tenfoot.conf /etc/udev/rules.d/60-tenfoot-uinput.rules /etc/systemd/journald.conf.d/tenfoot.conf
sudo raspi-config nonint do_boot_behaviour B1
echo "Removed. Reboot to get your console back: sudo reboot"
