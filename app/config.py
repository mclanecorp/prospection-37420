"""Configuration de l'application, lue depuis l'environnement."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VAR_DIR = Path(os.environ.get('VAR_DIR') or BASE_DIR / 'var')
MEDIA_DIR = VAR_DIR / 'media'
DB_PATH = Path(os.environ.get('DB_PATH') or VAR_DIR / 'social.db')

# Mot de passe partagé entre les membres du comité.
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'comite')

# Clé de signature des cookies de session. En production, la fixer via l'env
# sinon toutes les sessions sautent à chaque redémarrage.
SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# URL publique de l'app. Indispensable : Meta télécharge les images depuis
# cette adresse, elle doit donc être joignable depuis Internet.
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')

# Identifiants de l'app Meta (onglet Paramètres > Général du tableau de bord).
META_APP_ID = os.environ.get('META_APP_ID', '')
META_APP_SECRET = os.environ.get('META_APP_SECRET', '')
GRAPH_VERSION = os.environ.get('GRAPH_VERSION', 'v21.0')
GRAPH_URL = f'https://graph.facebook.com/{GRAPH_VERSION}'

# Mode simulation : aucune requête vers Meta, les publications sont simulées.
# Pratique pour prendre l'app en main avant d'avoir configuré Meta.
DRY_RUN = os.environ.get('DRY_RUN', '').lower() in ('1', 'true', 'yes')

# Fuseau utilisé pour la planification et l'affichage des dates.
TIMEZONE = os.environ.get('TIMEZONE', 'Europe/Paris')

# Permissions demandées lors de la connexion du compte Meta.
META_SCOPES = ','.join([
    'pages_show_list',
    'pages_manage_posts',
    'pages_read_engagement',
    'business_management',
    'instagram_basic',
    'instagram_content_publish',
    'instagram_manage_insights',
])

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}


def ensure_dirs():
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
