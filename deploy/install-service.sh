#!/usr/bin/env bash
# Устанавливает systemd-сервис для автозапуска StreamSync после перезагрузки сервера.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="streamsync"
UNIT="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запусти с sudo: sudo ./deploy/install-service.sh"
  exit 1
fi

RUN_USER="${SUDO_USER:-root}"
if [[ "$RUN_USER" == "root" ]]; then
  echo "Запускай через sudo от своего пользователя: sudo ./deploy/install-service.sh"
  exit 1
fi

if [[ ! -x "${ROOT}/strem_switcher/bin/python" ]]; then
  echo "Нет venv: cd ${ROOT} && python3 -m venv strem_switcher && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "${ROOT}/.env" ]]; then
  echo "Создай ${ROOT}/.env (см. .env.example)"
  exit 1
fi

sed \
  -e "s|__USER__|${RUN_USER}|g" \
  -e "s|__ROOT__|${ROOT}|g" \
  "${ROOT}/deploy/streamsync.service" > "${UNIT}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo ""
echo "✅ Сервис ${SERVICE_NAME} установлен и запущен."
echo "   Статус:  systemctl status ${SERVICE_NAME}"
echo "   Логи:    journalctl -u ${SERVICE_NAME} -f"
echo "   Стоп:    sudo systemctl stop ${SERVICE_NAME}"
echo "   После перезагрузки сервера бот поднимется сам."
