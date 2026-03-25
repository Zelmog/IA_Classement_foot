#!/bin/bash
# =============================================================
# Script de déploiement - IA Classement Foot
# Serveur Oracle Cloud (Ubuntu 24.04)
# =============================================================
#
# Usage:
#   chmod +x deploy.sh
#   sudo ./deploy.sh
#
# Prérequis : Ubuntu 24.04 sur Oracle Cloud (ARM ou x86)
# =============================================================

set -e

APP_DIR="/opt/ia-foot"
APP_USER="iafoot"
VENV_DIR="$APP_DIR/venv"
GUNICORN_PORT=5000
DOMAIN="ia-classement-foot.fr"

echo "=== IA Classement Foot — Déploiement (Ubuntu 24.04) ==="

# ── 1. Dépendances système ──────────────────────────────────
echo "[1/6] Installation des dépendances système..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx curl

# ── 2. Utilisateur dédié ────────────────────────────────────
echo "[2/6] Configuration de l'utilisateur..."
id -u $APP_USER &>/dev/null || useradd -r -m -s /bin/bash $APP_USER

# ── 3. Copier les fichiers ──────────────────────────────────
echo "[3/6] Copie des fichiers..."
mkdir -p $APP_DIR/data
cp -r modules templates webapp.py main.py requirements.txt $APP_DIR/
cp data/dernier_classement.json $APP_DIR/data/ 2>/dev/null || true
chown -R $APP_USER:$APP_USER $APP_DIR

# ── 4. Environnement Python ─────────────────────────────────
echo "[4/6] Configuration de l'environnement Python..."
sudo -u $APP_USER python3 -m venv $VENV_DIR
sudo -u $APP_USER $VENV_DIR/bin/pip install --quiet --upgrade pip
sudo -u $APP_USER $VENV_DIR/bin/pip install --quiet -r $APP_DIR/requirements.txt

# ── 5. Service systemd (1 worker, 4 threads) ────────────────
echo "[5/6] Configuration du service systemd..."
cat > /etc/systemd/system/ia-foot.service << EOF
[Unit]
Description=IA Classement Foot - Web Server
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$VENV_DIR/bin/gunicorn webapp:app \\
    --bind 127.0.0.1:$GUNICORN_PORT \\
    --workers 1 \\
    --threads 4 \\
    --timeout 300
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ia-foot
systemctl restart ia-foot

# ── 6. Nginx reverse proxy ──────────────────────────────────
echo "[6/6] Configuration de Nginx..."
cat > /etc/nginx/sites-available/ia-foot << 'NGINX'
server {
    listen 80;
    server_name ia-classement-foot.fr www.ia-classement-foot.fr;

    gzip on;
    gzip_types text/css application/json application/javascript;
    gzip_min_length 256;

    proxy_read_timeout 300;
    proxy_connect_timeout 60;
    proxy_send_timeout 300;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 4 32k;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/ia-foot /etc/nginx/sites-enabled/ia-foot
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# ── Firewall ────────────────────────────────────────────────
echo "Ouverture des ports 80 et 443..."
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
fi

# ── SSL (Let's Encrypt) ─────────────────────────────────────
echo ""
echo "=== Déploiement terminé ! ==="
echo ""
echo "  Application : http://$DOMAIN"
echo "  Gunicorn    : 127.0.0.1:$GUNICORN_PORT (interne)"
echo "  Nginx       : ports 80/443 (proxy)"
echo ""
echo "  Pour activer HTTPS :"
echo "    sudo apt install certbot python3-certbot-nginx"
echo "    sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN"
echo ""
echo "  Commandes utiles :"
echo "    sudo systemctl status ia-foot     # État de l'app"
echo "    sudo journalctl -u ia-foot -f     # Logs en temps réel"
echo "    sudo systemctl restart ia-foot    # Redémarrer l'app"
echo ""
echo "  ⚠️  Oracle Cloud : ouvrir les ports 80 et 443 dans les Security Lists"
echo ""
echo "  Pour HTTPS (recommandé) :"
echo "    sudo apt install certbot python3-certbot-nginx"
echo "    sudo certbot --nginx -d votre-domaine.com"
echo ""
