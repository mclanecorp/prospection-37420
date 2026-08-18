"""Orchestration de la publication d'un post vers tous ses comptes cibles."""
import logging
import secrets

from . import config, db, meta

log = logging.getLogger(__name__)


def media_urls(conn, publication_id):
    """URLs publiques des images, telles que Meta ira les télécharger."""
    rows = conn.execute(
        'SELECT token, mime FROM media WHERE publication_id = ? ORDER BY position, id',
        (publication_id,),
    ).fetchall()
    urls = []
    for row in rows:
        extension = config.ALLOWED_IMAGE_TYPES.get(row['mime'], '.jpg')
        urls.append(f'{config.PUBLIC_BASE_URL}/media/{row["token"]}{extension}')
    return urls


async def publish(publication_id):
    """Publie une publication sur chacune de ses cibles en attente.

    Chaque compte est traité indépendamment : l'échec d'Instagram ne doit pas
    empêcher la publication sur Facebook.
    """
    with db.session() as conn:
        publication = conn.execute(
            'SELECT * FROM publications WHERE id = ?', (publication_id,)
        ).fetchone()
        if publication is None:
            raise ValueError(f'Publication {publication_id} introuvable')
        targets = conn.execute(
            'SELECT t.*, a.platform, a.external_id, a.access_token, a.name '
            'FROM targets t JOIN accounts a ON a.id = t.account_id '
            'WHERE t.publication_id = ? AND t.status != ?',
            (publication_id, 'published'),
        ).fetchall()
        urls = media_urls(conn, publication_id)
        message = publication['message']

    results = []
    for target in targets:
        try:
            post_id, permalink = await _publish_one(target, message, urls)
            results.append((target['id'], 'published', post_id, permalink, None))
        except meta.MetaError as exc:
            log.warning('Publication %s échouée sur %s : %s',
                        publication_id, target['name'], exc)
            results.append((target['id'], 'failed', None, None, str(exc)))
        except Exception as exc:  # pragma: no cover - filet de sécurité
            log.exception('Erreur inattendue sur %s', target['name'])
            results.append((target['id'], 'failed', None, None, f'Erreur interne : {exc}'))

    with db.session() as conn:
        now = db.utcnow()
        for target_id, status, post_id, permalink, error in results:
            conn.execute(
                'UPDATE targets SET status = ?, external_post_id = ?, permalink = ?, '
                'error = ?, published_at = ? WHERE id = ?',
                (status, post_id, permalink, error,
                 now if status == 'published' else None, target_id),
            )
        _refresh_status(conn, publication_id, now)

    return results


async def _publish_one(target, message, urls):
    if config.DRY_RUN:
        fake_id = f'dryrun_{secrets.token_hex(6)}'
        return fake_id, f'https://example.invalid/{target["platform"]}/{fake_id}'
    if target['platform'] == 'facebook':
        return await meta.publish_facebook(
            target['external_id'], target['access_token'], message, urls)
    if target['platform'] == 'instagram':
        return await meta.publish_instagram(
            target['external_id'], target['access_token'], message, urls)
    raise meta.MetaError(f'Plateforme inconnue : {target["platform"]}')


def _refresh_status(conn, publication_id, now):
    """Recalcule l'état global d'une publication à partir de ses cibles."""
    rows = conn.execute(
        'SELECT status FROM targets WHERE publication_id = ?', (publication_id,)
    ).fetchall()
    states = {row['status'] for row in rows}
    if not states:
        status = 'draft'
    elif states == {'published'}:
        status = 'published'
    elif 'published' in states:
        status = 'partial'
    elif 'pending' in states:
        status = 'scheduled'
    else:
        status = 'failed'
    published_at = now if status in ('published', 'partial') else None
    conn.execute(
        'UPDATE publications SET status = ?, '
        'published_at = COALESCE(published_at, ?) WHERE id = ?',
        (status, published_at, publication_id),
    )
