#!/usr/bin/env python3
"""
Surveille la disponibilite de consoles PS5 chez Best Buy Canada et envoie
une notification push via ntfy.sh des qu'un article devient achetable.

Dependances : aucune (stdlib seulement).

Variables d'environnement :
  NTFY_TOPIC    (requis)  nom du topic ntfy, ex. "ps5-isaac-8f3kd"
  NTFY_SERVER   (option)  defaut https://ntfy.sh
  STATE_FILE    (option)  defaut state.json
  CHECK_ROUNDS  (option)  nombre de verifications par execution, defaut 9
  ROUND_DELAY   (option)  secondes entre chaque verification, defaut 30
  POSTAL_CODE   (option)  defaut G1S1A1 (Sillery / Quebec)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------- configuration

PRODUCTS = {
    "19446111": {
        "nom": "PS5 Slim 1 To (lecteur de disque)",
        "prix": "824,14 $",
        "url": "https://www.bestbuy.ca/en-ca/product/playstation-5-slim-1tb-console/19446111",
    },
    "19446112": {
        "nom": "PS5 Slim Digital Edition 825 Go",
        "prix": "754,14 $",
        "url": "https://www.bestbuy.ca/en-ca/product/playstation-5-slim-digital-edition-825gb-console/19446112",
    },
    "19492009": {
        "nom": "PS5 Pro",
        "prix": "1104,14 $",
        "url": "https://www.bestbuy.ca/en-ca/product/playstation-5-pro-console/19492009",
    },
    "18477929": {
        "nom": "PS5 Pro (2e fiche)",
        "prix": "1104,10 $",
        "url": "https://www.bestbuy.ca/en-ca/product/playstation-5-pro-console/18477929",
    },
}

# Magasins Best Buy autour de Quebec (code postal G1R), captures depuis le
# site. Sans le parametre "accept" ci-dessous, l'API ignore "locations" et
# renvoie pickup=NotAvailable pour tout : les deux vont ensemble.
LOCATIONS = ["335", "336", "907", "334", "313", "906", "271"]

AVAILABILITY_URL = (
    "https://www.bestbuy.ca/ecomm-api/availability/products"
    "?accept=application%2Fvnd.bestbuy.standardproduct.v1%2Bjson"
    "&accept-language=en-CA"
    "&locations={locations}"
    "&postalCode={postal}"
    "&skus={skus}"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
CHECK_ROUNDS = int(os.environ.get("CHECK_ROUNDS", "9"))
ROUND_DELAY = int(os.environ.get("ROUND_DELAY", "30"))
POSTAL_CODE = os.environ.get("POSTAL_CODE", "G1S1A1")

# Nombre d'echecs consecutifs avant d'avertir que la sonde est cassee
FAILURE_ALERT_THRESHOLD = 6

EASTERN = timezone(timedelta(hours=-5))

# ---------------------------------------------------------------- utilitaires


def log(msg):
    stamp = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S")
    print("[{}] {}".format(stamp, msg), flush=True)


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"produits": {}, "echecs": 0, "echec_signale": False}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def fetch_availability():
    """Retourne {sku: {"online": bool, "pickup": bool, "statut": str}}."""
    url = AVAILABILITY_URL.format(
        skus="%7C".join(PRODUCTS.keys()),
        postal=POSTAL_CODE,
        locations="%7C".join(LOCATIONS),
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8",
            "Referer": "https://www.bestbuy.ca/en-ca/category/ps5-consoles/17583383",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.load(resp)

    result = {}
    for entry in payload.get("availabilities", []):
        sku = str(entry.get("sku"))
        shipping = entry.get("shipping") or {}
        pickup = entry.get("pickup") or {}
        magasins = [
            {"nom": loc.get("name", "?"), "qte": loc.get("quantityOnHand", 0)}
            for loc in (pickup.get("locations") or [])
            if loc.get("hasInventory")
        ]
        result[sku] = {
            "online": bool(shipping.get("purchasable")),
            "pickup": bool(magasins) or bool(pickup.get("purchasable")),
            # Detail non conserve dans state.json : les quantites bougent sans
            # cesse et feraient committer le workflow a chaque execution.
            "magasins": magasins,
            "statut": "{} / {}".format(
                shipping.get("status", "?"), pickup.get("status", "?")
            ),
        }
    return result


def ntfy(title, body, priority="default", tags="", click=None):
    """Envoie une notification. Les en-tetes restent en ASCII pur :
    ntfy transporte les en-tetes en latin-1, donc les accents vont
    uniquement dans le corps du message (UTF-8)."""
    if not NTFY_TOPIC:
        log("NTFY_TOPIC absent : notification ignoree -> {}".format(title))
        return False

    headers = {
        "Title": title.encode("ascii", "replace").decode("ascii"),
        "Priority": priority,
        "Content-Type": "text/plain; charset=utf-8",
    }
    if tags:
        headers["Tags"] = tags
    if click:
        headers["Click"] = click

    req = urllib.request.Request(
        "{}/{}".format(NTFY_SERVER, NTFY_TOPIC),
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        log("Notification envoyee : {}".format(title))
        return True
    except urllib.error.URLError as exc:
        log("Echec envoi ntfy : {}".format(exc))
        return False


# ---------------------------------------------------------------- logique


def evaluer(state, dispo):
    """Compare la disponibilite au dernier etat connu et notifie les
    transitions indisponible -> disponible. Retourne True si l'etat a change."""
    change = False
    produits = state.setdefault("produits", {})

    for sku, info in PRODUCTS.items():
        courant = dispo.get(sku)
        if courant is None:
            log("{} : absent de la reponse de l'API".format(sku))
            continue

        precedent = produits.get(sku, {})
        etait_dispo = bool(precedent.get("online")) or bool(precedent.get("pickup"))
        est_dispo = courant["online"] or courant["pickup"]

        log(
            "{} {} -> en ligne={} cueillette={} ({})".format(
                sku, info["nom"], courant["online"], courant["pickup"], courant["statut"]
            )
        )

        if est_dispo and not etait_dispo:
            canaux = []
            if courant["online"]:
                canaux.append("livraison en ligne")
            if courant["pickup"]:
                canaux.append("cueillette en magasin")
            detail = ""
            if courant.get("magasins"):
                detail = "\nMagasins : " + ", ".join(
                    "{} ({})".format(m["nom"], m["qte"])
                    for m in courant["magasins"]
                )
            corps = (
                "{nom} — {prix}\n"
                "Disponible : {canaux}{detail}\n\n"
                "Vas-y tout de suite, ça part vite.\n{url}"
            ).format(
                nom=info["nom"],
                prix=info["prix"],
                canaux=" + ".join(canaux),
                detail=detail,
                url=info["url"],
            )
            ntfy(
                title="EN STOCK - {}".format(
                    info["nom"].replace("é", "e").replace("è", "e")
                ),
                body=corps,
                priority="urgent",
                tags="rotating_light,video_game",
                click=info["url"],
            )

        if est_dispo != etait_dispo:
            change = True

        # "vu" ne bouge que si quelque chose a change, sinon state.json
        # differe a chaque execution et le workflow commit pour rien.
        identique = (
            precedent.get("online") == courant["online"]
            and precedent.get("pickup") == courant["pickup"]
            and precedent.get("statut") == courant["statut"]
            and precedent.get("vu")
        )
        produits[sku] = {
            "online": courant["online"],
            "pickup": courant["pickup"],
            "statut": courant["statut"],
            "vu": precedent["vu"] if identique
            else datetime.now(EASTERN).isoformat(timespec="seconds"),
        }

    return change


def main():
    state = load_state()
    change = False
    succes = False

    for tour in range(1, CHECK_ROUNDS + 1):
        try:
            dispo = fetch_availability()
            succes = True
            state["echecs"] = 0
            if state.get("echec_signale"):
                state["echec_signale"] = False
                change = True
                ntfy(
                    title="Sonde PS5 de nouveau fonctionnelle",
                    body="L'API de Best Buy repond a nouveau. La surveillance reprend.",
                    priority="low",
                    tags="white_check_mark",
                )
            if evaluer(state, dispo):
                change = True
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            log("Tour {}/{} : echec de la requete ({})".format(tour, CHECK_ROUNDS, exc))

        if tour < CHECK_ROUNDS:
            time.sleep(ROUND_DELAY)

    if not succes:
        state["echecs"] = int(state.get("echecs", 0)) + 1
        change = True
        log("Aucune requete reussie. Compteur d'echecs : {}".format(state["echecs"]))
        if state["echecs"] >= FAILURE_ALERT_THRESHOLD and not state.get("echec_signale"):
            state["echec_signale"] = True
            ntfy(
                title="Sonde PS5 en panne",
                body=(
                    "L'API de disponibilite de Best Buy ne repond plus depuis "
                    "plusieurs executions. Best Buy bloque peut-être les adresses "
                    "IP de GitHub Actions. Vérifie les logs du workflow."
                ),
                priority="high",
                tags="warning",
            )

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
