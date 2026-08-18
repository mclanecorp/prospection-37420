# Guide de mise en route

Ce guide part du principe que personne dans le comité n'est développeur.
Comptez une petite heure la première fois. Une fois fait, c'est fait pour de bon.

---

## Ce qu'il faut avant de commencer

1. **Une Page Facebook** au nom du comité. Un profil personnel ou un groupe ne
   suffit pas : l'API ne publie que sur des Pages.
2. **Un compte Instagram professionnel** relié à cette Page.
   Dans l'app Instagram : *Paramètres → Type de compte → Passer en compte
   professionnel*, puis relier la Page Facebook. C'est gratuit, ça ne change
   rien pour vos abonnés, et c'est obligatoire pour publier via l'API.
3. **Un compte Facebook personnel administrateur de la Page** — c'est avec
   celui-là que vous ferez la configuration.

---

## Étape 1 — Créer l'app Meta

L'« app Meta » est juste un jeton d'autorisation entre votre serveur et Facebook.
Elle reste privée, personne ne la voit, et **elle n'a pas besoin d'être validée
par Meta** tant qu'elle ne publie que sur vos propres comptes.

1. Allez sur <https://developers.facebook.com/apps> et connectez-vous avec votre
   compte Facebook personnel.
2. **Créer une application**. Choisissez le cas d'usage qui parle de gérer des
   Pages et publier du contenu (les libellés bougent régulièrement chez Meta ;
   prenez « Autre » puis le type **Entreprise** si vous hésitez).
3. Donnez-lui un nom, par exemple `Publications comité`.

⚠️ **Laissez l'app en mode Développement.** C'est justement ce mode qui vous
dispense de la revue de Meta. Ne cliquez pas sur « Passer en mode Live ».

## Étape 2 — Ajouter les produits nécessaires

Dans le menu de gauche, ajoutez ces deux produits :

- **Connexion Facebook** (*Facebook Login*) — sert à relier vos comptes à l'app.
- **API Instagram** (*Instagram Graph API* / *Instagram*) — sert à publier sur
  Instagram. Choisissez l'option qui passe par la connexion Facebook, pas la
  connexion Instagram directe.

## Étape 3 — Donner un rôle aux membres du comité

*Rôles de l'app → Rôles → Ajouter des personnes.*

Ajoutez en **Administrateur** ou **Testeur** chaque membre du comité qui devra
publier. Chacun reçoit une invitation à accepter.

En mode Développement, seules ces personnes peuvent utiliser l'app — c'est
exactement ce que vous voulez.

## Étape 4 — Récupérer les identifiants

*Paramètres → Général.* Notez :

- l'**identifiant de l'application** (App ID) ;
- la **clé secrète** (App Secret) — cliquez sur « Afficher ».

⚠️ La clé secrète est un mot de passe. Elle ne se met **jamais** dans un message,
un mail, ni dans le dépôt de code. Elle va uniquement dans la configuration du
serveur (étape 6).

## Étape 5 — Déclarer l'adresse de retour

*Connexion Facebook → Paramètres → URI de redirection OAuth valides.*

Collez-y exactement :

```
https://VOTRE-ADRESSE/connect/callback
```

en remplaçant `VOTRE-ADRESSE` par l'adresse publique de votre app.
La page **Réglages** de l'application affiche l'adresse exacte à recopier.

---

## Étape 6 — Installer l'application

L'app a besoin de tourner en permanence (pour les publications programmées et la
collecte des statistiques).

👉 **Pour un hébergement clé en main, suivez [DEPLOIEMENT.md](DEPLOIEMENT.md)** :
tout y est détaillé clic par clic. La suite de cette section ne sert que si vous
installez l'app vous-même sur votre propre serveur.

### Ce qu'il faut configurer

Les réglages passent par des variables d'environnement. Le fichier
`.env.example` liste tout ; recopiez-le en `.env` et remplissez :

| Variable | À quoi ça sert |
|---|---|
| `APP_PASSWORD` | Le mot de passe partagé entre les membres du comité. |
| `SECRET_KEY` | Signe les cookies. Générez-la au hasard, gardez-la stable. |
| `PUBLIC_BASE_URL` | L'adresse publique en `https://`. **Meta vient y chercher les photos** : si elle est fausse, les publications avec image échoueront. |
| `META_APP_ID` / `META_APP_SECRET` | Les identifiants de l'étape 4. |
| `TIMEZONE` | `Europe/Paris`. |
| `DRY_RUN` | `1` pour essayer sans rien publier, `0` en vrai. |

### Lancer avec Docker

```bash
docker build -t comite-publications .
docker run -d --name comite -p 8000:8000 \
  --env-file .env -v comite-data:/data \
  comite-publications
```

Le volume `comite-data` contient la base et les photos : **sans lui, tout
l'historique disparaît au premier redéploiement.**

### Lancer sans Docker

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Mettez l'app derrière un reverse proxy en HTTPS (Caddy, Nginx, ou le HTTPS
automatique de votre hébergeur). Facebook refuse les adresses en `http://`.

---

## Étape 7 — Connecter les comptes

1. Ouvrez votre app, entrez le mot de passe partagé.
2. Allez dans **Réglages → Connecter / actualiser les comptes Meta**.
3. Facebook demande l'autorisation : **cochez bien la Page du comité** dans la
   liste. Si vous la décochez, rien ne fonctionnera.
4. De retour sur l'app, la Page et le compte Instagram apparaissent dans la
   liste des comptes.

Si Instagram n'apparaît pas : le compte n'est pas en professionnel, ou il n'est
pas relié à cette Page. Reprenez le point 2 des prérequis.

## Étape 8 — Enregistrer vos groupes Facebook

Toujours dans **Réglages**, ajoutez vos groupes (nom + lien).
Ils apparaîtront ensuite sur chaque publication sous forme de liste à cocher.

---

## Au quotidien

1. **Nouveau post** → texte + photo(s) → *Publier* (ou programmer une date).
2. Le post part sur la Page et sur Instagram.
3. Dans la section **Partage dans les groupes**, cliquez sur *Ouvrir le post de
   la Page*, puis utilisez le bouton **Partager → dans un groupe** de Facebook.
   Cochez le groupe dans l'app au fur et à mesure.
4. Les statistiques se rafraîchissent toutes les six heures ; le bouton
   *Rafraîchir les stats* force une mise à jour immédiate.

---

## Ce que l'app ne peut pas faire, et pourquoi

- **Publier automatiquement dans les groupes Facebook.** Meta a supprimé l'API
  Groupes le 22 avril 2024, pour tout le monde. Aucun outil, même payant, ne le
  fait plus. D'où la liste de partage assistée.
- **Remonter les statistiques des groupes.** Facebook ne les expose pas à
  l'extérieur. Le champ « vues » de chaque groupe est là si vous voulez recopier
  le chiffre à la main.
- **Publier un texte seul sur Instagram.** Instagram exige au moins une image.
  Un post sans photo part uniquement sur Facebook.

---

## Petits pépins fréquents

| Symptôme | Cause la plus probable |
|---|---|
| « URL blocked » / « URI de redirection non autorisée » | L'URI de l'étape 5 ne correspond pas exactement (oubli du `https://`, slash en trop). |
| La publication Instagram échoue sur l'image | `PUBLIC_BASE_URL` est faux, ou le serveur n'est pas joignable depuis Internet. Meta doit pouvoir télécharger la photo. |
| Aucune Page trouvée à la connexion | La Page n'a pas été cochée dans l'écran d'autorisation Facebook, ou vous n'en êtes pas administrateur. |
| Les statistiques restent à zéro | Normal les premières heures : Meta met du temps à calculer la portée d'un post récent. |
| Tout le monde est déconnecté après un redémarrage | `SECRET_KEY` n'est pas fixée dans la configuration : elle est alors régénérée à chaque démarrage. |

## Sécurité, en deux phrases

La base `var/social.db` contient les jetons d'accès à vos comptes : elle donne le
droit de publier en votre nom. Ne la partagez pas, ne la versionnez pas, et
choisissez un vrai mot de passe pour `APP_PASSWORD`.
