#!/usr/bin/env bash
# Install the Polymarket maker on a small Debian box.
#
# Creates the venv, installs the package, creates the runtime directories and
# installs the systemd units. It writes no credentials and it starts nothing.
#
#   bash deploy/install.sh
#
# The environment file is NOT created here, because it holds the CLOB
# credentials. The script prints the command to run next.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${PMM_APP_DIR:-/opt/pmm}"
RUN_USER="${PMM_USER:-pmm}"
ENV_DIR="/etc/pmm-mm"
ENV_FILE="${ENV_DIR}/pmm.env"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "install.sh must run as root" >&2
    exit 1
fi

echo "==> creating the service account"
if ! id -u "${RUN_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${RUN_USER}"
fi

echo "==> copying the package to ${APP_DIR}"
mkdir -p "${APP_DIR}"
# Copy the source tree without the venv, the caches or the git metadata.
rsync -a --delete \
    --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    "${SRC_DIR}/" "${APP_DIR}/"

echo "==> creating the venv"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --quiet "${APP_DIR}"
"${APP_DIR}/.venv/bin/pip" install --quiet pytest || true

echo "==> creating the runtime directories"
mkdir -p /var/lib/pmm/journal /var/lib/pmm/reports
chown -R "${RUN_USER}:${RUN_USER}" /var/lib/pmm
chmod 750 /var/lib/pmm

echo "==> installing the systemd units"
install -m 644 "${APP_DIR}/deploy/pmm-mm.service" /etc/systemd/system/pmm-mm.service
install -m 644 "${APP_DIR}/deploy/pmm-selftune.service" /etc/systemd/system/pmm-selftune.service
install -m 644 "${APP_DIR}/deploy/pmm-selftune.timer" /etc/systemd/system/pmm-selftune.timer
install -m 644 "${APP_DIR}/deploy/pmm-merge.service" /etc/systemd/system/pmm-merge.service
install -m 644 "${APP_DIR}/deploy/pmm-merge.timer" /etc/systemd/system/pmm-merge.timer
install -m 644 "${APP_DIR}/deploy/pmm-rescue.service" /etc/systemd/system/pmm-rescue.service
install -m 644 "${APP_DIR}/deploy/pmm-rescue.timer" /etc/systemd/system/pmm-rescue.timer
install -m 644 "${APP_DIR}/deploy/pmm-harvest.service" /etc/systemd/system/pmm-harvest.service
install -m 644 "${APP_DIR}/deploy/pmm-harvest.timer" /etc/systemd/system/pmm-harvest.timer
install -m 644 "${APP_DIR}/deploy/pmm-redeem.service" /etc/systemd/system/pmm-redeem.service
install -m 644 "${APP_DIR}/deploy/pmm-redeem.timer" /etc/systemd/system/pmm-redeem.timer
systemctl daemon-reload

echo "==> preparing the environment file"
mkdir -p "${ENV_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
    install -m 640 -o root -g "${RUN_USER}" "${APP_DIR}/deploy/pmm.env.example" "${ENV_FILE}"
    echo "    created ${ENV_FILE} from the example. Fill it in before starting."
else
    echo "    ${ENV_FILE} already exists, leaving it alone."
fi

cat <<EOF

Installed. Next:

    1. Edit the environment:
         ${ENV_FILE}

       Set POLY_API_KEY, POLY_API_SECRET and POLY_API_PASSPHRASE for the CLOB
       credentials. Set POLY_OWNER_PK only when the account's signing key is
       available; without it the service stays in dry-run mode.
       Set PMM_RUN_ARGS to the loop's arguments (add --paper to stay dry).
       Set POLY_RELAYER_API_KEY / POLY_RELAYER_ADDRESS for the merge timer.

    2. Start the maker and the hourly tick:
         systemctl start pmm-mm.service
         systemctl start pmm-selftune.timer

    3. Watch it:
         journalctl -u pmm-mm -f
         ls /var/lib/pmm/reports
EOF
