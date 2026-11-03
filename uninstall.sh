#!/bin/sh
# Undoes install.sh. Run as your admin user. Keeps the TV's user and its settings unless you pass --purge.
# Installed packages stay.
set -u
TV=tenfoot
if id "$TV" >/dev/null 2>&1; then
  RUN=/run/user/$(id -u "$TV")
  sudo -u "$TV" -H env XDG_RUNTIME_DIR="$RUN" systemctl --user disable --now tenfoot tenfoot-spotify tenfoot-airplay tenfoot-wallpapers 2>/dev/null
  sudo sed -i '/^# tenfoot kiosk/,/^fi$/d' "/home/$TV/.profile"
  sudo rm -f /home/$TV/.config/systemd/user/tenfoot*.service
  sudo loginctl disable-linger "$TV"
  sudo rm -rf "/etc/systemd/system/user@$(id -u "$TV").service.d/tenfoot-restart.conf"
fi
sudo systemctl disable --now tenfoot-update.timer 2>/dev/null
sudo rm -rf /var/lib/tenfoot-update /usr/local/sbin/tenfoot-update /etc/systemd/system/tenfoot-update.service \
  /etc/systemd/system/tenfoot-update-now.service /etc/systemd/system/tenfoot-update.timer /etc/systemd/system/tenfoot-reboot-stuck.service
sudo rm -f /etc/chromium/policies/managed/tenfoot.json /etc/modules-load.d/tenfoot.conf /etc/udev/rules.d/60-tenfoot-uinput.rules \
  /etc/systemd/journald.conf.d/tenfoot.conf /etc/polkit-1/rules.d/50-tenfoot.rules \
  /etc/NetworkManager/dnsmasq-shared.d/tenfoot.conf /etc/sysctl.d/60-tenfoot.conf /etc/systemd/system/getty@tty1.service.d/tenfoot-autologin.conf /usr/local/bin/tenfoot
sudo systemctl daemon-reload
if [ "${1:-}" = --purge ] && id "$TV" >/dev/null 2>&1; then
  sudo pkill -KILL -u "$TV" 2>/dev/null
  sleep 1
  sudo userdel --remove "$TV" 2>/dev/null
fi
echo "Removed. Reboot to get your console back: sudo reboot"
