#!/usr/bin/env bash
# Настройка HTTPS для StreamSync через nginx + Let's Encrypt
# ТОЛЬКО для пустого VPS без своего nginx/сайта.
# Если SSL уже есть — добавь location из deploy/nginx/existing-site-locations.conf
# Использование: sudo ./deploy/setup-https.sh stream.твой-домен.ru
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Использование: sudo $0 stream.example.com [email@example.com]"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Запусти с sudo"
  exit 1
fi

apt-get update -qq
apt-get install -y nginx certbot python3-certbot-nginx

mkdir -p /var/www/certbot
CONF="/etc/nginx/sites-available/streamsync"

cat > "$CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf "$CONF" /etc/nginx/sites-enabled/streamsync
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if [[ -n "$EMAIL" ]]; then
  echo "Получаем сертификат Let's Encrypt для ${DOMAIN}..."
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL"
else
  echo "Запусти certbot (укажи свой email):"
  echo "  sudo certbot --nginx -d ${DOMAIN}"
  echo "Затем: sudo nginx -t && sudo systemctl reload nginx"
fi

echo ""
echo "Готово. В .env укажи:"
echo "  PUBLIC_BASE_URL=https://${DOMAIN}"
echo ""
echo "В Twitch Redirect URL:"
echo "  https://${DOMAIN}/oauth/twitch"
echo ""
echo "Бот по-прежнему запускай: ./run.sh (порт 8080 локально)"
