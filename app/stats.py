"""Collecte des statistiques et mise en série temporelle."""
import logging
import random
from datetime import datetime, timedelta, timezone

from . import config, db, meta

log = logging.getLogger(__name__)

METRIC_LABELS = {
    'views': 'Vues',
    'reach': 'Personnes touchées',
    'likes': "J'aime",
    'comments': 'Commentaires',
    'shares': 'Partages',
    'saves': 'Enregistrements',
}
# Métriques tracées sur le tableau de bord, dans cet ordre.
CHART_METRICS = ['views', 'likes', 'comments', 'shares']
# Au-delà, un post ne bouge quasiment plus : inutile d'interroger Meta.
ACTIVE_WINDOW_DAYS = 45


async def refresh_target(target_row):
    """Interroge Meta pour une cible publiée et renvoie les compteurs."""
    if config.DRY_RUN:
        return _simulated_metrics(target_row)
    if target_row['platform'] == 'facebook':
        return await meta.facebook_metrics(
            target_row['external_post_id'], target_row['access_token'])
    return await meta.instagram_metrics(
        target_row['external_post_id'], target_row['access_token'])


def _simulated_metrics(target_row):
    """Chiffres plausibles en mode simulation, croissants dans le temps."""
    seed = int(target_row['id'])
    rng = random.Random(seed * 7919 + int(datetime.now(timezone.utc).timestamp()) // 3600)
    published = target_row['published_at'] or db.utcnow()
    age_hours = max(1, int(
        (datetime.now(timezone.utc) - datetime.fromisoformat(published)).total_seconds() // 3600))
    base = min(age_hours, 240) * (6 + seed % 5)
    views = base + rng.randint(0, 40)
    return {
        'views': views,
        'reach': int(views * 0.82),
        'likes': int(views * 0.06) + rng.randint(0, 3),
        'comments': int(views * 0.012) + rng.randint(0, 2),
        'shares': int(views * 0.008),
        'saves': int(views * 0.01),
        'permalink': target_row['permalink'],
    }


def _targets_to_refresh(conn, publication_id=None):
    query = (
        'SELECT t.*, a.platform, a.access_token FROM targets t '
        'JOIN accounts a ON a.id = t.account_id '
        "WHERE t.status = 'published' AND t.external_post_id IS NOT NULL"
    )
    params = []
    if publication_id is not None:
        query += ' AND t.publication_id = ?'
        params.append(publication_id)
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ACTIVE_WINDOW_DAYS)).isoformat()
        query += ' AND (t.published_at IS NULL OR t.published_at >= ?)'
        params.append(cutoff)
    return conn.execute(query, params).fetchall()


async def collect(publication_id=None):
    """Prend une photo des compteurs et l'enregistre. Renvoie (ok, erreurs)."""
    with db.session() as conn:
        targets = _targets_to_refresh(conn, publication_id)

    rows, failures = [], []
    for target in targets:
        try:
            rows.append((target, await refresh_target(target)))
        except meta.MetaError as exc:
            log.warning('Statistiques indisponibles pour la cible %s : %s', target['id'], exc)
            failures.append((target['id'], str(exc)))

    with db.session() as conn:
        captured_at = db.utcnow()
        for target, metrics in rows:
            conn.execute(
                'INSERT INTO snapshots (target_id, captured_at, views, reach, likes, '
                'comments, shares, saves) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (target['id'], captured_at, metrics.get('views'), metrics.get('reach'),
                 metrics.get('likes'), metrics.get('comments'), metrics.get('shares'),
                 metrics.get('saves')),
            )
            if metrics.get('permalink') and not target['permalink']:
                conn.execute('UPDATE targets SET permalink = ? WHERE id = ?',
                             (metrics['permalink'], target['id']))
    return len(rows), failures


def series(conn, target_id, metric):
    """Série (instant, valeur) d'une métrique, pour tracer une courbe."""
    if metric not in METRIC_LABELS:
        raise ValueError(f'Métrique inconnue : {metric}')
    query = (
        f'SELECT captured_at, {metric} AS value FROM snapshots '
        f'WHERE target_id = ? AND {metric} IS NOT NULL ORDER BY captured_at'
    )
    rows = conn.execute(query, (target_id,)).fetchall()
    return [(row['captured_at'], row['value']) for row in rows]


def totals(conn, publication_id):
    """Somme des derniers compteurs connus, tous comptes confondus."""
    targets = conn.execute(
        'SELECT id FROM targets WHERE publication_id = ?', (publication_id,)
    ).fetchall()
    summed = {key: 0 for key in METRIC_LABELS}
    seen = False
    for target in targets:
        snapshot = db.latest_snapshot(conn, target['id'])
        if snapshot is None:
            continue
        seen = True
        for key in summed:
            summed[key] += snapshot[key] or 0
    return summed if seen else None
