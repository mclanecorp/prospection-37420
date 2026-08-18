"""Client de l'API Graph de Meta : connexion, publication et statistiques.

Tout passe par une seule app Meta laissée en mode Développement : les comptes
du comité y ont un rôle (admin / testeur), ce qui évite l'App Review réservée
aux apps qui publient pour des comptes tiers.
"""
import asyncio
import logging

import httpx

from . import config

log = logging.getLogger(__name__)

# Métriques demandées en priorité. Meta en retire régulièrement : la requête
# est rejouée sans les métriques refusées plutôt que d'échouer en bloc.
FB_INSIGHT_METRICS = ['post_impressions', 'post_impressions_unique', 'post_clicks']
IG_INSIGHT_METRICS = ['views', 'reach', 'saved', 'shares', 'total_interactions']


class MetaError(RuntimeError):
    """Erreur renvoyée par l'API Graph, avec un message lisible."""

    def __init__(self, message, code=None, subcode=None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode


def _raise_for_payload(payload):
    error = payload.get('error') if isinstance(payload, dict) else None
    if not error:
        return
    message = error.get('error_user_msg') or error.get('message') or 'Erreur Meta inconnue'
    raise MetaError(message, error.get('code'), error.get('error_subcode'))


async def _request(method, path, *, token=None, params=None, data=None, timeout=60.0):
    url = path if path.startswith('http') else f'{config.GRAPH_URL}/{path.lstrip("/")}'
    params = dict(params or {})
    if token:
        params['access_token'] = token
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, params=params, data=data)
    try:
        payload = response.json()
    except ValueError:
        raise MetaError(f'Réponse illisible de Meta (HTTP {response.status_code})')
    _raise_for_payload(payload)
    if response.status_code >= 400:
        raise MetaError(f'Meta a répondu HTTP {response.status_code}')
    return payload


async def get(path, token=None, params=None):
    return await _request('GET', path, token=token, params=params)


async def post(path, token=None, data=None):
    return await _request('POST', path, token=token, data=data)


# --- Connexion du compte -------------------------------------------------

def login_url(redirect_uri, state):
    from urllib.parse import urlencode
    query = urlencode({
        'client_id': config.META_APP_ID,
        'redirect_uri': redirect_uri,
        'state': state,
        'scope': config.META_SCOPES,
        'response_type': 'code',
    })
    return f'https://www.facebook.com/{config.GRAPH_VERSION}/dialog/oauth?{query}'


async def exchange_code(code, redirect_uri):
    payload = await get('oauth/access_token', params={
        'client_id': config.META_APP_ID,
        'client_secret': config.META_APP_SECRET,
        'redirect_uri': redirect_uri,
        'code': code,
    })
    return payload['access_token']


async def long_lived_token(short_token):
    """Convertit un jeton court (1-2 h) en jeton long (~60 jours).

    Les jetons de Page dérivés d'un jeton utilisateur longue durée n'expirent
    pas, c'est eux qu'on stocke pour publier.
    """
    payload = await get('oauth/access_token', params={
        'grant_type': 'fb_exchange_token',
        'client_id': config.META_APP_ID,
        'client_secret': config.META_APP_SECRET,
        'fb_exchange_token': short_token,
    })
    return payload['access_token']


async def list_pages(user_token):
    payload = await get('me/accounts', token=user_token, params={
        'fields': 'id,name,access_token',
        'limit': 100,
    })
    return payload.get('data', [])


async def instagram_for_page(page_id, page_token):
    """Renvoie le compte Instagram professionnel relié à une Page, ou None."""
    payload = await get(page_id, token=page_token, params={
        'fields': 'instagram_business_account{id,username,name}',
    })
    account = payload.get('instagram_business_account')
    if not account:
        return None
    return {
        'id': account['id'],
        'name': account.get('username') or account.get('name') or 'Instagram',
    }


# --- Publication ---------------------------------------------------------

async def publish_facebook(page_id, page_token, message, image_urls):
    """Publie sur une Page et renvoie (post_id, permalien)."""
    if not image_urls:
        created = await post(f'{page_id}/feed', token=page_token, data={'message': message})
        post_id = created['id']
    elif len(image_urls) == 1:
        created = await post(f'{page_id}/photos', token=page_token, data={
            'url': image_urls[0],
            'message': message,
        })
        # /photos renvoie l'id de la photo ; post_id est l'id du post de Page.
        post_id = created.get('post_id') or created['id']
    else:
        # Album : on téléverse chaque photo non publiée, puis on les rattache.
        media_ids = []
        for url in image_urls:
            uploaded = await post(f'{page_id}/photos', token=page_token, data={
                'url': url,
                'published': 'false',
            })
            media_ids.append(uploaded['id'])
        data = {'message': message}
        for index, media_id in enumerate(media_ids):
            data[f'attached_media[{index}]'] = f'{{"media_fbid":"{media_id}"}}'
        created = await post(f'{page_id}/feed', token=page_token, data=data)
        post_id = created['id']

    permalink = await _facebook_permalink(post_id, page_token)
    return post_id, permalink


async def _facebook_permalink(post_id, token):
    try:
        payload = await get(post_id, token=token, params={'fields': 'permalink_url'})
        return payload.get('permalink_url')
    except MetaError:
        return None


async def publish_instagram(ig_user_id, token, caption, image_urls, poll_seconds=90):
    """Publie sur Instagram et renvoie (media_id, permalien).

    Instagram impose au moins une image : un post texte seul est impossible.
    """
    if not image_urls:
        raise MetaError("Instagram exige au moins une image : ajoutez une photo "
                        "ou décochez Instagram pour cette publication.")

    if len(image_urls) == 1:
        container = await post(f'{ig_user_id}/media', token=token, data={
            'image_url': image_urls[0],
            'caption': caption,
        })
        creation_id = container['id']
    else:
        children = []
        for url in image_urls:
            child = await post(f'{ig_user_id}/media', token=token, data={
                'image_url': url,
                'is_carousel_item': 'true',
            })
            children.append(child['id'])
        container = await post(f'{ig_user_id}/media', token=token, data={
            'media_type': 'CAROUSEL',
            'children': ','.join(children),
            'caption': caption,
        })
        creation_id = container['id']

    await _wait_for_container(creation_id, token, poll_seconds)
    published = await post(f'{ig_user_id}/media_publish', token=token, data={
        'creation_id': creation_id,
    })
    media_id = published['id']
    permalink = await _instagram_permalink(media_id, token)
    return media_id, permalink


async def _wait_for_container(creation_id, token, poll_seconds):
    """Instagram prépare le média de façon asynchrone : on attend qu'il soit prêt."""
    deadline = poll_seconds
    delay = 2
    while deadline > 0:
        payload = await get(creation_id, token=token, params={
            'fields': 'status_code,status',
        })
        status = payload.get('status_code')
        if status == 'FINISHED':
            return
        if status == 'ERROR':
            raise MetaError(payload.get('status') or "Instagram n'a pas pu préparer l'image.")
        await asyncio.sleep(delay)
        deadline -= delay
        delay = min(delay * 2, 10)
    raise MetaError("Instagram n'a pas fini de préparer l'image dans le temps imparti.")


async def _instagram_permalink(media_id, token):
    try:
        payload = await get(media_id, token=token, params={'fields': 'permalink'})
        return payload.get('permalink')
    except MetaError:
        return None


# --- Statistiques --------------------------------------------------------

async def _insights(node_id, token, metrics):
    """Récupère des insights en abandonnant les métriques refusées.

    Meta retire des métriques sans prévenir ; on préfère des chiffres partiels
    à une page de tableau de bord vide.
    """
    remaining = list(metrics)
    values = {}
    for _ in range(len(metrics)):
        if not remaining:
            break
        try:
            payload = await get(f'{node_id}/insights', token=token,
                                params={'metric': ','.join(remaining)})
        except MetaError as exc:
            dropped = [m for m in remaining if m in str(exc)]
            if not dropped:
                log.warning('Insights indisponibles pour %s : %s', node_id, exc)
                break
            remaining = [m for m in remaining if m not in dropped]
            continue
        for entry in payload.get('data', []):
            series = entry.get('values') or []
            if series:
                values[entry['name']] = series[-1].get('value')
        break
    return values


async def facebook_metrics(post_id, token):
    fields = ('permalink_url,shares,'
              'likes.summary(true).limit(0),comments.summary(true).limit(0)')
    payload = await get(post_id, token=token, params={'fields': fields})
    insights = await _insights(post_id, token, FB_INSIGHT_METRICS)
    likes = (payload.get('likes') or {}).get('summary', {}).get('total_count')
    comments = (payload.get('comments') or {}).get('summary', {}).get('total_count')
    return {
        'views': insights.get('post_impressions'),
        'reach': insights.get('post_impressions_unique'),
        'likes': likes,
        'comments': comments,
        'shares': (payload.get('shares') or {}).get('count'),
        'saves': None,
        'permalink': payload.get('permalink_url'),
    }


async def instagram_metrics(media_id, token):
    payload = await get(media_id, token=token, params={
        'fields': 'like_count,comments_count,permalink',
    })
    insights = await _insights(media_id, token, IG_INSIGHT_METRICS)
    return {
        'views': insights.get('views'),
        'reach': insights.get('reach'),
        'likes': payload.get('like_count'),
        'comments': payload.get('comments_count'),
        'shares': insights.get('shares'),
        'saves': insights.get('saved'),
        'permalink': payload.get('permalink'),
    }
