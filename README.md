# Reel Agent Server

Serveur de montage vidéo automatique pour Reel Agent.

## Stack
- Python + Flask
- FFmpeg pour le montage
- Déployé sur Railway

## Variables d'environnement requises
- `TELEGRAM_TOKEN` : Token du bot Telegram
- `GROUP_ID` : ID du groupe Telegram (-5213698485)
- `PORT` : Port (Railway le gère automatiquement)

## Endpoint
- `GET /` : Health check
- `POST /render` : Lance un montage vidéo
