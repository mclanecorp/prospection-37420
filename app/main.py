"""Application web du comité : publier une fois, suivre partout."""
import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import charts, config, db, meta, publisher, stats

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger(__name__)

app = FastAPI(title='Publication comité des fêtes')

TEMPLATE_DIR = Path(__file__).parent / 'templates'
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
app.mount('/static', StaticFiles(directory=str(Path(__file__).parent / 'static')), name='static')

LOCAL_TZ = ZoneInfo(config.TIMEZONE)
scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

STATUS_LABELS = {
    'draft': 'Brouillon',
    'scheduled': 'Programmée',
    'published': 'Publiée',
    'partial': 'Partiellement publiée',
    'failed': 'Échec',
    'pending': 'En attente',
}


# --- Filtres d'affichage --------------------------------------------------

def local_datetime(value, fmt='%d/%m/%Y à %H:%M'):
    if not value:
        return ''
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(LOCAL_TZ).strftime(fmt)


def thousands(value):
    if value in (None, ''):
        return '—'
    return f'{int(value):,}'.replace(',', ' ')


templates.env.filters['dt'] = local_datetime
templates.env.filters['num'] = thousands
templates.env.globals['STATUS_LABELS'] = STATUS_LABELS
templates.env.globals['METRIC_LABELS'] = stats.METRIC_LABELS


# --- Session et messages --------------------------------------------------

def is_authenticated(request):
    return bool(request.session.get('auth'))


def flash(request, message, level='info'):
    request.session.setdefault('flashes', []).append({'message': message, 'level': level})


def pop_flashes(request):
    flashes = request.session.pop('flashes', [])
    return flashes


def render(request, template, **context):
    context.setdefault('flashes', pop_flashes(request))
    context.setdefault('dry_run', config.DRY_RUN)
    return templates.TemplateResponse(request, template, context)


def redirect(url, status_code=303):
    return RedirectResponse(url, status_code=status_code)


@app.middleware('http')
async def require_login(request: Request, call_next):
    """Tout est privé sauf la connexion, les fichiers statiques et les médias.

    Les médias doivent rester publics : c'est Meta qui vient les télécharger
    pour construire la publication.
    """
    open_paths = ('/login', '/static', '/media', '/healthz')
    if request.url.path.startswith(open_paths) or is_authenticated(request):
        return await call_next(request)
    return redirect('/login')


# Ajoutée après le contrôle d'accès pour l'envelopper : la session doit être
# lisible quand `require_login` s'exécute.
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY,
                   session_cookie='comite_session', max_age=60 * 60 * 24 * 30,
                   https_only=config.PUBLIC_BASE_URL.startswith('https://'))


# --- Authentification -----------------------------------------------------

@app.get('/login', response_class=HTMLResponse)
async def login_form(request: Request):
    if is_authenticated(request):
        return redirect('/')
    return render(request, 'login.html')


@app.post('/login')
async def login(request: Request, password: str = Form('')):
    if secrets.compare_digest(password, config.APP_PASSWORD):
        request.session['auth'] = True
        return redirect('/')
    flash(request, 'Mot de passe incorrect.', 'error')
    return redirect('/login')


@app.get('/logout')
async def logout(request: Request):
    request.session.clear()
    return redirect('/login')


@app.get('/healthz')
async def healthz():
    return {'status': 'ok'}


# --- Tableau de bord ------------------------------------------------------

@app.get('/', response_class=HTMLResponse)
async def dashboard(request: Request):
    with db.session() as conn:
        publications = conn.execute(
            'SELECT * FROM publications ORDER BY COALESCE(published_at, scheduled_at, '
            'created_at) DESC LIMIT 50'
        ).fetchall()
        rows = []
        for publication in publications:
            targets = conn.execute(
                'SELECT t.*, a.platform, a.name FROM targets t '
                'JOIN accounts a ON a.id = t.account_id WHERE t.publication_id = ?',
                (publication['id'],),
            ).fetchall()
            shared = conn.execute(
                'SELECT COUNT(*) AS n FROM group_shares WHERE publication_id = ? '
                'AND shared_at IS NOT NULL', (publication['id'],)
            ).fetchone()['n']
            rows.append({
                'publication': publication,
                'targets': targets,
                'totals': stats.totals(conn, publication['id']),
                'shared_groups': shared,
                'thumbnail': _thumbnail(conn, publication['id']),
            })
        group_count = conn.execute(
            'SELECT COUNT(*) AS n FROM fb_groups WHERE active = 1').fetchone()['n']
        account_count = len(db.active_accounts(conn))
        recent = _recent_totals(conn)
    return render(request, 'dashboard.html', rows=rows, group_count=group_count,
                  account_count=account_count, recent=recent)


def _thumbnail(conn, publication_id):
    row = conn.execute(
        'SELECT token, mime FROM media WHERE publication_id = ? ORDER BY position, id LIMIT 1',
        (publication_id,),
    ).fetchone()
    if not row:
        return None
    extension = config.ALLOWED_IMAGE_TYPES.get(row['mime'], '.jpg')
    return f'/media/{row["token"]}{extension}'


def _recent_totals(conn, days=30):
    """Cumul des derniers compteurs connus sur les publications récentes."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    targets = conn.execute(
        'SELECT t.id FROM targets t JOIN publications p ON p.id = t.publication_id '
        "WHERE t.status = 'published' AND COALESCE(p.published_at, p.created_at) >= ?",
        (cutoff,),
    ).fetchall()
    summed = {key: 0 for key in stats.METRIC_LABELS}
    found = False
    for target in targets:
        snapshot = db.latest_snapshot(conn, target['id'])
        if snapshot is None:
            continue
        found = True
        for key in summed:
            summed[key] += snapshot[key] or 0
    summed['posts'] = len(targets)
    return summed if found else None


# --- Rédaction et publication --------------------------------------------

@app.get('/compose', response_class=HTMLResponse)
async def compose_form(request: Request):
    with db.session() as conn:
        accounts = db.active_accounts(conn)
    return render(request, 'compose.html', accounts=accounts)


@app.post('/compose')
async def compose(request: Request):
    form = await request.form()
    message = (form.get('message') or '').strip()
    account_ids = [int(value) for value in form.getlist('accounts')]
    scheduled_raw = (form.get('scheduled_at') or '').strip()
    action = form.get('action') or 'publish'
    uploads = [item for item in form.getlist('images')
               if isinstance(item, UploadFile) and item.filename]

    if not message and not uploads:
        flash(request, 'Il faut au moins un texte ou une image.', 'error')
        return redirect('/compose')
    if not account_ids and action != 'draft':
        flash(request, 'Sélectionnez au moins un compte.', 'error')
        return redirect('/compose')

    scheduled_at = None
    if scheduled_raw:
        try:
            naive = datetime.fromisoformat(scheduled_raw)
        except ValueError:
            flash(request, 'Date de programmation illisible.', 'error')
            return redirect('/compose')
        scheduled_at = naive.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).isoformat()

    try:
        stored = await _store_uploads(uploads)
    except ValueError as exc:
        flash(request, str(exc), 'error')
        return redirect('/compose')

    with db.session() as conn:
        status = 'draft' if action == 'draft' else ('scheduled' if scheduled_at else 'draft')
        cursor = conn.execute(
            'INSERT INTO publications (message, status, scheduled_at, created_at) '
            'VALUES (?, ?, ?, ?)', (message, status, scheduled_at, db.utcnow()))
        publication_id = cursor.lastrowid
        for position, item in enumerate(stored):
            conn.execute(
                'INSERT INTO media (publication_id, filename, mime, token, position) '
                'VALUES (?, ?, ?, ?, ?)',
                (publication_id, item['filename'], item['mime'], item['token'], position))
        for account_id in account_ids:
            conn.execute(
                'INSERT INTO targets (publication_id, account_id) VALUES (?, ?)',
                (publication_id, account_id))
        # Prépare la liste de partage en groupes, à cocher au fur et à mesure.
        for group in conn.execute(
                'SELECT id FROM fb_groups WHERE active = 1').fetchall():
            conn.execute(
                'INSERT OR IGNORE INTO group_shares (publication_id, group_id) '
                'VALUES (?, ?)', (publication_id, group['id']))

    if action == 'draft':
        flash(request, 'Brouillon enregistré.')
    elif scheduled_at:
        flash(request, f'Publication programmée pour le {local_datetime(scheduled_at)}.')
    else:
        return await publish_now(request, publication_id)
    return redirect(f'/publications/{publication_id}')


async def _store_uploads(uploads):
    stored = []
    for upload in uploads:
        content = await upload.read()
        if len(content) > config.MAX_UPLOAD_BYTES:
            raise ValueError(f'« {upload.filename} » dépasse 12 Mo.')
        mime = upload.content_type or ''
        if mime not in config.ALLOWED_IMAGE_TYPES:
            raise ValueError(f'« {upload.filename} » : format non accepté '
                             '(JPEG, PNG ou WebP uniquement).')
        token = secrets.token_urlsafe(24)
        extension = config.ALLOWED_IMAGE_TYPES[mime]
        (config.MEDIA_DIR / f'{token}{extension}').write_bytes(content)
        stored.append({'filename': upload.filename, 'mime': mime, 'token': token})
    return stored


@app.post('/publications/{publication_id}/publish')
async def publish_now(request: Request, publication_id: int):
    try:
        results = await publisher.publish(publication_id)
    except ValueError as exc:
        flash(request, str(exc), 'error')
        return redirect('/')

    published = [r for r in results if r[1] == 'published']
    failed = [r for r in results if r[1] == 'failed']
    if published and not failed:
        flash(request, f'Publié sur {len(published)} compte(s).', 'success')
    elif published:
        flash(request, f'Publié sur {len(published)} compte(s), '
                       f'{len(failed)} en échec.', 'warning')
    elif failed:
        flash(request, 'Aucune publication n\'a abouti. Détail plus bas.', 'error')
    else:
        flash(request, 'Rien à publier : aucun compte en attente.', 'warning')

    if published:
        # Premier relevé immédiat, pour que la courbe démarre à la publication.
        _spawn(_safe_collect(publication_id))
    return redirect(f'/publications/{publication_id}')


# asyncio ne garde qu'une référence faible aux tâches : sans ce jeu, une
# collecte lancée en arrière-plan peut être ramassée avant de s'exécuter.
_background_tasks = set()


def _spawn(coroutine):
    task = asyncio.create_task(coroutine)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _safe_collect(publication_id=None):
    try:
        await stats.collect(publication_id)
    except Exception:  # pragma: no cover - tâche de fond
        log.exception('Collecte des statistiques échouée')


# --- Détail d'une publication --------------------------------------------

@app.get('/publications/{publication_id}', response_class=HTMLResponse)
async def publication_detail(request: Request, publication_id: int):
    with db.session() as conn:
        publication = conn.execute(
            'SELECT * FROM publications WHERE id = ?', (publication_id,)).fetchone()
        if publication is None:
            flash(request, 'Publication introuvable.', 'error')
            return redirect('/')
        targets = conn.execute(
            'SELECT t.*, a.platform, a.name FROM targets t '
            'JOIN accounts a ON a.id = t.account_id WHERE t.publication_id = ? '
            'ORDER BY a.platform', (publication_id,)).fetchall()
        images = [
            f'/media/{row["token"]}'
            f'{config.ALLOWED_IMAGE_TYPES.get(row["mime"], ".jpg")}'
            for row in conn.execute(
                'SELECT token, mime FROM media WHERE publication_id = ? '
                'ORDER BY position, id', (publication_id,)).fetchall()
        ]
        latest = {t['id']: db.latest_snapshot(conn, t['id']) for t in targets}
        figures = _build_charts(conn, targets)
        shares = conn.execute(
            'SELECT gs.*, g.name, g.url FROM group_shares gs '
            'JOIN fb_groups g ON g.id = gs.group_id '
            'WHERE gs.publication_id = ? AND g.active = 1 ORDER BY g.position, g.name',
            (publication_id,)).fetchall()
        page_permalink = next(
            (t['permalink'] for t in targets
             if t['platform'] == 'facebook' and t['permalink']), None)
        totals = stats.totals(conn, publication_id)

    return render(request, 'publication.html', publication=publication, targets=targets,
                  images=images, latest=latest, figures=figures, shares=shares,
                  page_permalink=page_permalink, totals=totals)


def _build_charts(conn, targets):
    """Une courbe par métrique, une série par compte (petits multiples).

    Chaque métrique garde son échelle : mélanger vues et commentaires sur un
    même axe écraserait la seconde.
    """
    figures = []
    for metric in stats.CHART_METRICS:
        series = []
        for target in targets:
            points = stats.series(conn, target['id'], metric)
            if points:
                series.append({'name': target['name'],
                               'platform': target['platform'],
                               'points': points})
        figures.append(charts.line_chart(stats.METRIC_LABELS[metric], series))
    return figures


@app.post('/publications/{publication_id}/refresh')
async def refresh_stats(request: Request, publication_id: int):
    collected, failures = await stats.collect(publication_id)
    if collected:
        flash(request, f'Statistiques mises à jour ({collected} compte(s)).', 'success')
    if failures:
        flash(request, 'Certaines statistiques sont indisponibles : '
                       + ' · '.join(message for _, message in failures), 'warning')
    if not collected and not failures:
        flash(request, 'Rien à rafraîchir pour l\'instant.', 'warning')
    return redirect(f'/publications/{publication_id}')


@app.post('/publications/{publication_id}/delete')
async def delete_publication(request: Request, publication_id: int):
    with db.session() as conn:
        rows = conn.execute('SELECT token, mime FROM media WHERE publication_id = ?',
                            (publication_id,)).fetchall()
        conn.execute('DELETE FROM publications WHERE id = ?', (publication_id,))
    for row in rows:
        extension = config.ALLOWED_IMAGE_TYPES.get(row['mime'], '.jpg')
        (config.MEDIA_DIR / f'{row["token"]}{extension}').unlink(missing_ok=True)
    flash(request, 'Publication supprimée du suivi (le post reste en ligne sur '
                   'Facebook et Instagram).')
    return redirect('/')


# --- Partage en groupes (manuel, l'API Groupes n'existe plus) -------------

@app.post('/publications/{publication_id}/groups/{group_id}')
async def toggle_group_share(request: Request, publication_id: int, group_id: int,
                             manual_views: str = Form('')):
    with db.session() as conn:
        row = conn.execute(
            'SELECT * FROM group_shares WHERE publication_id = ? AND group_id = ?',
            (publication_id, group_id)).fetchone()
        views = int(manual_views) if manual_views.strip().isdigit() else None
        if row and row['shared_at']:
            conn.execute('UPDATE group_shares SET shared_at = NULL, manual_views = ? '
                         'WHERE id = ?', (views, row['id']))
        elif row:
            conn.execute('UPDATE group_shares SET shared_at = ?, manual_views = ? '
                         'WHERE id = ?', (db.utcnow(), views, row['id']))
        else:
            conn.execute(
                'INSERT INTO group_shares (publication_id, group_id, shared_at, '
                'manual_views) VALUES (?, ?, ?, ?)',
                (publication_id, group_id, db.utcnow(), views))
    return redirect(f'/publications/{publication_id}#groupes')


# --- Médias (publics : Meta vient les chercher ici) -----------------------

@app.get('/media/{name}')
async def media_file(name: str):
    # Un token d'URL non devinable tient lieu d'autorisation.
    path = (config.MEDIA_DIR / name).resolve()
    if not str(path).startswith(str(config.MEDIA_DIR.resolve())) or not path.is_file():
        return HTMLResponse('Introuvable', status_code=404)
    return FileResponse(path, headers={'Cache-Control': 'public, max-age=86400'})


# --- Réglages -------------------------------------------------------------

@app.get('/reglages', response_class=HTMLResponse)
async def settings_page(request: Request):
    with db.session() as conn:
        accounts = conn.execute(
            'SELECT * FROM accounts ORDER BY platform, name').fetchall()
        groups = conn.execute(
            'SELECT * FROM fb_groups ORDER BY position, name').fetchall()
    configured = bool(config.META_APP_ID and config.META_APP_SECRET)
    return render(request, 'settings.html', accounts=accounts, groups=groups,
                  configured=configured, public_url=config.PUBLIC_BASE_URL,
                  redirect_uri=f'{config.PUBLIC_BASE_URL}/connect/callback')


@app.get('/connect')
async def connect(request: Request):
    if not (config.META_APP_ID and config.META_APP_SECRET):
        flash(request, "Renseignez d'abord META_APP_ID et META_APP_SECRET.", 'error')
        return redirect('/reglages')
    state = secrets.token_urlsafe(16)
    request.session['oauth_state'] = state
    return redirect(meta.login_url(f'{config.PUBLIC_BASE_URL}/connect/callback', state))


@app.get('/connect/callback')
async def connect_callback(request: Request, code: str = '', state: str = '',
                           error_description: str = ''):
    expected = request.session.pop('oauth_state', None)
    if error_description:
        flash(request, f'Facebook a refusé la connexion : {error_description}', 'error')
        return redirect('/reglages')
    if not code or not state or state != expected:
        flash(request, 'Connexion interrompue ou invalide, réessayez.', 'error')
        return redirect('/reglages')

    try:
        short_token = await meta.exchange_code(
            code, f'{config.PUBLIC_BASE_URL}/connect/callback')
        user_token = await meta.long_lived_token(short_token)
        pages = await meta.list_pages(user_token)
    except meta.MetaError as exc:
        flash(request, f'Connexion échouée : {exc}', 'error')
        return redirect('/reglages')

    if not pages:
        flash(request, "Aucune Page trouvée sur ce compte. Vérifiez que vous êtes bien "
                       "administrateur d'une Page (un profil ou un groupe ne suffit pas).",
              'error')
        return redirect('/reglages')

    added = []
    for page in pages:
        instagram = None
        try:
            instagram = await meta.instagram_for_page(page['id'], page['access_token'])
        except meta.MetaError as exc:
            log.info('Pas de compte Instagram lisible pour %s : %s', page['name'], exc)
        with db.session() as conn:
            _upsert_account(conn, 'facebook', page['id'], page['name'],
                            page['access_token'])
            added.append(page['name'])
            if instagram:
                _upsert_account(conn, 'instagram', instagram['id'], instagram['name'],
                                page['access_token'], page_id=page['id'])
                added.append(f'@{instagram["name"]}')

    flash(request, 'Comptes connectés : ' + ', '.join(added), 'success')
    if not any(name.startswith('@') for name in added):
        flash(request, "Aucun compte Instagram relié n'a été trouvé. Vérifiez que "
                       "l'Instagram est en compte professionnel et relié à la Page.",
              'warning')
    return redirect('/reglages')


def _upsert_account(conn, platform, external_id, name, token, page_id=None):
    conn.execute(
        'INSERT INTO accounts (platform, external_id, name, access_token, page_id, '
        'connected_at) VALUES (?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(platform, external_id) DO UPDATE SET name = excluded.name, '
        'access_token = excluded.access_token, page_id = excluded.page_id, '
        'active = 1, connected_at = excluded.connected_at',
        (platform, external_id, name, token, page_id, db.utcnow()))


@app.post('/accounts/{account_id}/toggle')
async def toggle_account(request: Request, account_id: int):
    with db.session() as conn:
        conn.execute('UPDATE accounts SET active = 1 - active WHERE id = ?', (account_id,))
    return redirect('/reglages')


@app.post('/accounts/{account_id}/delete')
async def delete_account(request: Request, account_id: int):
    with db.session() as conn:
        conn.execute('DELETE FROM accounts WHERE id = ?', (account_id,))
    flash(request, 'Compte déconnecté.')
    return redirect('/reglages')


def _safe_url(value):
    """Ne garde que des liens http(s) : le reste finirait dans un href."""
    value = (value or '').strip()
    if not value:
        return ''
    return value if value.lower().startswith(('http://', 'https://')) else ''


@app.post('/groups')
async def add_group(request: Request, name: str = Form(...), url: str = Form('')):
    name = name.strip()
    if not name:
        flash(request, 'Nom de groupe vide.', 'error')
        return redirect('/reglages')
    cleaned_url = _safe_url(url)
    if url.strip() and not cleaned_url:
        flash(request, 'Lien ignoré : seules les adresses http:// ou https:// '
                       'sont acceptées.', 'warning')
    with db.session() as conn:
        position = conn.execute(
            'SELECT COALESCE(MAX(position), 0) + 1 AS p FROM fb_groups').fetchone()['p']
        cursor = conn.execute(
            'INSERT INTO fb_groups (name, url, position) VALUES (?, ?, ?)',
            (name, cleaned_url, position))
        # Le nouveau groupe apparaît aussi sur les publications déjà en cours.
        for publication in conn.execute(
                "SELECT id FROM publications WHERE status IN ('published', 'partial', "
                "'scheduled', 'draft')").fetchall():
            conn.execute('INSERT OR IGNORE INTO group_shares (publication_id, group_id) '
                         'VALUES (?, ?)', (publication['id'], cursor.lastrowid))
    flash(request, f'Groupe « {name} » ajouté.', 'success')
    return redirect('/reglages')


@app.post('/groups/{group_id}/toggle')
async def toggle_group(request: Request, group_id: int):
    with db.session() as conn:
        conn.execute('UPDATE fb_groups SET active = 1 - active WHERE id = ?', (group_id,))
    return redirect('/reglages')


@app.post('/groups/{group_id}/delete')
async def delete_group(request: Request, group_id: int):
    with db.session() as conn:
        conn.execute('DELETE FROM fb_groups WHERE id = ?', (group_id,))
    flash(request, 'Groupe supprimé.')
    return redirect('/reglages')


# --- Tâches de fond -------------------------------------------------------

async def run_due_publications():
    """Publie les posts programmés dont l'heure est passée."""
    now = db.utcnow()
    with db.session() as conn:
        due = conn.execute(
            "SELECT id FROM publications WHERE status = 'scheduled' "
            'AND scheduled_at IS NOT NULL AND scheduled_at <= ?', (now,)).fetchall()
    for publication in due:
        log.info('Publication programmée %s : envoi', publication['id'])
        try:
            await publisher.publish(publication['id'])
        except Exception:  # pragma: no cover - tâche de fond
            log.exception('Publication programmée %s échouée', publication['id'])


@app.on_event('startup')
async def startup():
    db.init()
    scheduler.add_job(run_due_publications, 'interval', minutes=1,
                      id='publications_dues', max_instances=1)
    scheduler.add_job(_safe_collect, 'interval', hours=6,
                      id='collecte_stats', max_instances=1)
    scheduler.start()
    if config.APP_PASSWORD == 'comite':
        log.warning("APP_PASSWORD est resté sur sa valeur par défaut : "
                    "n'importe qui pourrait publier au nom du comité.")
    if not os.environ.get('SECRET_KEY'):
        log.warning('SECRET_KEY non fixée : les sessions sauteront à chaque '
                    'redémarrage du serveur.')
    log.info('Application démarrée (simulation=%s, url publique=%s)',
             config.DRY_RUN, config.PUBLIC_BASE_URL)


@app.on_event('shutdown')
async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
