# Surveillance PS5 — Best Buy Canada → ntfy

Vérifie aux ~30 secondes si une console PS5 redevient achetable chez Best Buy
Canada et envoie une notification push sur ton téléphone. Tourne gratuitement
sur GitHub Actions. Aucune dépendance Python.

## Consoles surveillées

| Code web | Modèle | Prix |
|---|---|---|
| 19446111 | PS5 Slim 1 To (lecteur de disque) | 824,14 $ |
| 19446112 | PS5 Slim Digital Edition 825 Go | 754,14 $ |
| 19492009 | PS5 Pro | 1104,14 $ |
| 18477929 | PS5 Pro (2e fiche Best Buy) | 1104,10 $ |

Les quatre étaient en rupture au moment de la mise en place. Pour en ajouter
ou en retirer, modifie le dictionnaire `PRODUCTS` au haut de `check_stock.py` —
le code web est le dernier segment de l'URL du produit.

## Comment ça marche

Le script interroge l'API de disponibilité de Best Buy :

```
https://www.bestbuy.ca/ecomm-api/availability/products?accept-language=en-CA&skus=19446111%7C19492009&postalCode=G1S1A1
```

Elle retourne du JSON. Le signal utilisé n'est pas le texte du statut mais le
booléen `shipping.purchasable`, beaucoup plus stable que de comparer des
chaînes comme `SoldOutOnline` ou `InStockOnlineOnly` :

```json
{"availabilities":[{"pickup":{"purchasable":false,"status":"NotAvailable"},
  "shipping":{"purchasable":false,"status":"SoldOutOnline"},"sku":"19446111"}]}
```

Une notification part uniquement sur la **transition** indisponible →
disponible. Tant que l'article reste en stock, tu ne reçois rien de plus. S'il
repart en rupture puis revient, tu es réalerté. L'état précédent est conservé
dans `state.json`, que le workflow réécrit dans le dépôt.

Le cron de GitHub tourne aux 5 minutes et n'est pas ponctuel à la minute. Pour
compenser, chaque exécution fait 9 vérifications espacées de 30 secondes
(`CHECK_ROUNDS` / `ROUND_DELAY`), ce qui donne une couverture quasi continue.

## Installation

**1. Installe ntfy sur ton téléphone**

L'app s'appelle « ntfy » (iOS App Store / Google Play / F-Droid). Choisis un
nom de sujet long et imprévisible — n'importe qui connaissant le nom peut lire
et écrire sur le sujet. Par exemple `ps5-qc-7h2mk9xp`. Abonne-toi dans l'app.

**2. Crée le dépôt**

Mets-le **public** : les dépôts publics ont des minutes GitHub Actions
illimitées. Un dépôt privé n'a que 2 000 minutes/mois, et un cron aux 5 minutes
en consomme environ 8 000. Il n'y a rien de sensible dans le code — le nom du
sujet ntfy vit dans un secret.

```bash
git init && git add . && git commit -m "Surveillance PS5 Best Buy"
gh repo create bb-ps5-watch --public --source=. --push
```

**3. Ajoute le secret**

Dépôt → Settings → Secrets and variables → Actions → New repository secret :

| Nom | Valeur |
|---|---|
| `NTFY_TOPIC` | ton nom de sujet, ex. `ps5-qc-7h2mk9xp` |

Variables optionnelles (onglet *Variables*) : `NTFY_SERVER` si tu héberges ton
propre ntfy, `POSTAL_CODE` si tu veux un autre secteur que Québec.

**4. Active et teste**

Onglet Actions → autorise les workflows → « Surveillance PS5 Best Buy » →
*Run workflow*. Les logs montrent chaque console et son état.

**5. Vérifie que l'alerte fonctionne vraiment**

Ne te fie pas à un log silencieux. Ajoute temporairement un article en stock à
`PRODUCTS`, lance le workflow à la main, confirme que le push arrive, puis
retire-le :

```python
"19491570": {
    "nom": "TEST - manette DualSense",
    "prix": "0 $",
    "url": "https://www.bestbuy.ca/en-ca/product/19491570",
},
```

## Limites connues

**La cueillette en magasin n'est pas fiable.** Le script lit
`pickup.purchasable` et alerte dessus, mais lors des tests ce champ est resté
à `NotAvailable` même pour une manette DualSense réellement disponible en
magasin, et le paramètre `postalCode` n'a rien changé. Best Buy garde
probablement le magasin sélectionné dans un cookie de session que le script
n'a pas. **Considère la détection en ligne comme le signal solide, et la
cueillette comme un bonus qui s'allumera peut-être.** Pour les consoles, les
réapprovisionnements passent de toute façon presque toujours par le web
d'abord. Si tu veux la cueillette de façon fiable, il faut piloter un vrai
navigateur (Playwright) avec un magasin choisi — plus lourd, à faire seulement
si le besoin se confirme.

**Best Buy peut bloquer les IP de GitHub Actions.** Le site est derrière un
CDN qui filtre parfois les plages de centres de données. Le script compte ses
échecs et t'envoie un push d'avertissement après 6 exécutions infructueuses
d'affilée, pour que tu ne croies pas à tort que tout va bien. Si ça arrive :
fais tourner le script sur un petit VPS, sur un Raspberry Pi, ou en
`launchd`/cron sur un Mac qui ne dort pas.

**Les accents dans les en-têtes.** ntfy transporte les en-têtes HTTP en
latin-1, donc le titre est volontairement sans accents. Le corps du message est
en UTF-8 et garde les accents.

## Fichiers

```
check_stock.py                 la sonde
.github/workflows/stock.yml    cron aux 5 min + sauvegarde de l'état
state.json                     dernier état connu (réécrit par le workflow)
```
