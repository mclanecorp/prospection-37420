# Mettre l'application en ligne (Render)

Ce document couvre l'hébergement. La configuration côté Facebook/Instagram est
dans [GUIDE.md](GUIDE.md) — les deux se croisent à l'étape 4, suivez cet ordre.

**Durée : environ 30 minutes.** Aucun logiciel à installer sur votre ordinateur.

---

## Ce que ça coûte

Le plan **Starter de Render, environ 7 $ par mois** (~6,50 €).

Le plan gratuit ne convient pas, et ce n'est pas une question de confort :

- il met le service **en veille au bout de 15 minutes** d'inactivité — vos
  publications programmées ne partiraient pas et les statistiques ne seraient
  pas collectées ;
- il **n'accepte pas de disque persistant** — votre historique et vos photos
  disparaîtraient à chaque redéploiement.

Si ce budget ne passe pas, dites-le-moi : un petit serveur à 4 €/mois revient
moins cher, au prix d'une installation plus manuelle.

---

## Étape 1 — Choisir la branche à déployer

Le code est actuellement sur la branche `claude/multi-network-publishing-app-oek1dr`.

Deux possibilités :

- **fusionner cette branche dans `main`** (le plus simple pour la suite : Render
  suivra `main` et se mettra à jour tout seul) ;
- ou **pointer Render sur cette branche** à l'étape 3.

Si vous voulez la fusion, demandez-le-moi, je prépare la demande de fusion.

## Étape 2 — Créer le compte Render

1. Allez sur <https://render.com> et créez un compte — **connectez-vous avec
   GitHub**, c'est ce qui permettra à Render de lire le dépôt.
2. Autorisez Render à accéder au dépôt `prospection-37420`.

## Étape 3 — Créer le service

1. Dans Render : **New → Blueprint**.
2. Choisissez le dépôt `prospection-37420`, et la branche décidée à l'étape 1.
3. Render détecte le fichier `render.yaml` et propose de créer le service
   **publications-comite**. Il demande quelques valeurs :

| Valeur demandée | Quoi mettre |
|---|---|
| `APP_PASSWORD` | Le mot de passe que les membres du comité taperont pour entrer. Choisissez-en un vrai. |
| `META_APP_ID` | Laissez vide pour l'instant — étape 5. |
| `META_APP_SECRET` | Laissez vide pour l'instant — étape 5. |
| `PUBLIC_BASE_URL` | Mettez `https://exemple.invalid` provisoirement — on ne connaît pas encore la vraie adresse. |

4. Lancez la création. Le premier déploiement prend quelques minutes.

⚠️ Ne touchez pas à `SECRET_KEY` : Render la génère seul, et elle doit rester
stable — sinon tout le monde est déconnecté à chaque redémarrage.

## Étape 4 — Récupérer l'adresse et la renseigner

Une fois le déploiement terminé, Render affiche l'adresse du service, du type :

```
https://publications-comite.onrender.com
```

1. Copiez-la.
2. Dans **Environment**, remplacez `PUBLIC_BASE_URL` par cette adresse exacte,
   **sans barre oblique à la fin**.
3. Enregistrez : Render redéploie automatiquement.

Cette adresse est importante à deux titres : c'est celle que vous ouvrirez sur
vos téléphones, et c'est là que **Meta vient télécharger les photos** au moment
de publier. Si elle est fausse, les publications avec image échoueront.

Vérifiez que ça répond : ouvrez l'adresse, la page de mot de passe doit
apparaître. Vous pouvez déjà entrer et vous promener — il n'y aura simplement
aucun compte connecté.

## Étape 5 — Créer l'app Meta

C'est le moment de faire les **étapes 1 à 5 de [GUIDE.md](GUIDE.md)**. Vous avez
maintenant l'adresse à déclarer comme URI de redirection :

```
https://VOTRE-ADRESSE.onrender.com/connect/callback
```

Puis revenez dans Render, **Environment**, et remplissez `META_APP_ID` et
`META_APP_SECRET`. Enregistrez ; Render redéploie.

## Étape 6 — Connecter les comptes

Ouvrez l'application → **Réglages → Connecter les comptes Meta**.
Cochez bien la Page du comité dans l'écran d'autorisation Facebook.

La Page et le compte Instagram apparaissent dans la liste. Ajoutez vos groupes
juste en dessous.

## Étape 7 — Un vrai essai

Publiez un vrai post, avec une photo, sur les deux réseaux. Vérifiez qu'il
apparaît bien sur la Page et sur Instagram, puis attendez quelques heures et
regardez si les statistiques remontent.

C'est le seul test qui compte : tout le reste a été vérifié, mais rien ne
remplace une vraie publication.

---

## Ensuite

- **Mettre à jour l'app** : à chaque nouveau code poussé sur la branche suivie,
  Render redéploie tout seul. Vos données ne bougent pas, elles sont sur le
  disque.
- **Ajouter un membre au comité** : donnez-lui l'adresse et le mot de passe
  partagé. Pensez aussi à lui donner un rôle sur l'app Meta (étape 3 du guide)
  s'il doit lui-même connecter des comptes.
- **Changer le mot de passe** : dans Render, **Environment**, modifiez
  `APP_PASSWORD` et enregistrez.

## Si ça coince

| Symptôme | À vérifier |
|---|---|
| La page ne s'ouvre pas du tout | Le déploiement est-il terminé et vert dans Render ? Regardez l'onglet **Logs**. |
| « URL blocked » à la connexion Facebook | L'URI de redirection de l'étape 5 doit correspondre **exactement**, `https://` inclus, sans barre oblique finale. |
| La publication Instagram échoue sur l'image | `PUBLIC_BASE_URL` est faux ou contient une barre oblique finale. |
| Tout le monde est déconnecté sans arrêt | `SECRET_KEY` a été modifiée ou supprimée. Laissez celle générée par Render. |
| L'historique a disparu | Le disque n'est pas monté. Vérifiez dans Render que le disque `donnees` est bien attaché sur `/data`. |

## Autres hébergeurs

Le `Dockerfile` est standard : Railway, Fly.io, Scaleway ou Clever Cloud
fonctionnent aussi. Deux points à respecter partout :

1. un **volume persistant monté sur `/data`** (variable `VAR_DIR=/data`) ;
2. un service **qui ne se met pas en veille**, sinon les publications
   programmées et la collecte des statistiques ne tournent pas.
