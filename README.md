# gardeco-social

Auto-publication programmée sur **Instagram + Facebook** (@gardecoch) via la Graph API,
et **Pinterest** (@gardeco) via l'API v5.
Première campagne : **Beatbot été 2026** (11 posts, 07.07 → 14.08, 2/semaine, 18h30 CH).

## Comment ça marche

- `schedule.json` — les posts (heure UTC, plateformes, type, URLs images, légende FR+DE).
- `media/` — les visuels (JPG 1080×1350), servis en CDN via **jsDelivr**.
- `publish.py` — publie les posts dus et pas encore publiés (IG + FB). Idempotent.
- `state/published.json` — état (committé par le workflow après chaque publication).
- `.github/workflows/publish.yml` — **cron GitHub Actions** : 16:30 UTC (18h30 CH) + rattrapage 17:15 UTC.

Un post n'est publié que si `publish_at_utc` est passé **et** qu'il n'est pas déjà dans `state`.
Les deux horaires cron + l'état committé garantissent : jamais de double-post, rattrapage si un run saute.

## Secrets (Settings → Secrets → Actions)

| Secret | Valeur |
|---|---|
| `META_TOKEN` | Token de **Page** Gardeco (n'expire pas) |
| `IG_USER_ID` | `17841470367810433` (@gardecoch) |
| `FB_PAGE_ID` | `518330814689805` (Page Gardeco) |
| `PUSHOVER_TOKEN` / `PUSHOVER_USER` | (optionnel) notifications |
| `PINTEREST_APP_ID` / `PINTEREST_APP_SECRET` | App « Gardeco Social » (App ID `1580225`), portail dev Pinterest |
| `PINTEREST_REFRESH_TOKEN` | Refresh token OAuth (~1 an), généré par `pinterest_auth.py login` |

## Tester / piloter (onglet **Actions** → *beatbot-publish* → *Run workflow*)

- **Simulation** : `dry = 1` (défaut) → liste ce qui serait publié, ne poste rien.
- **Publier un post précis maintenant** : `dry = 0`, `only = 02` (ignore l'heure).
- **Tout laisser tourner** : ne rien faire — le cron s'occupe de tout.

En local :
```bash
DRY=1 META_TOKEN=… IG_USER_ID=17841470367810433 FB_PAGE_ID=518330814689805 python publish.py
```

## Pinterest

- Ajouter `"pinterest"` aux `platforms` d'un post + un bloc dédié :
  ```json
  "pinterest": {"board_id": "…", "title": "≤100 c", "description": "≤800 c",
                "link": "https://gardeco.ch/…", "alt_text": "…"}
  ```
  `board_id` requis ; `title`/`description` retombent sur la légende (tronquée) si absents ;
  un carrousel devient un pin multi-images.
- Auth : `pinterest_auth.py` — `login` (flow OAuth complet, celui qu'on filme pour la demande
  d'accès Standard), `whoami`, `refresh`, `secrets`. Tokens dans
  `~/.config/claude-seo/pinterest-social.json` ; l'access token (30 j) est renouvelé à chaque
  run via le refresh token (~1 an).
- ⚠️ **App en accès Trial : les pins créés sont sandbox** (visibles par nous seuls, l'API répond
  200 + un id quand même). Publics seulement une fois l'app en **accès Standard**. Runbook :
  `~/Pro/Gardeco/Marketing/Social/pinterest/standard-access-runbook.md`.

## Calendrier

Voir `schedule.json`. Source éditoriale (légendes, angles) :
`~/Pro/Gardeco/Marketing/Social/campaigns/beatbot-ete-2026/`.

## Notes

- Fuseau : cron en UTC. 18h30 CH été (CEST) = 16:30 UTC. Campagne 100 % en été → pas de bascule DST.
- Carrousels 03/07 : jeu de slides **FR** + légende bilingue FR+DE (1 seule version publiée).
- Isolé volontairement de la base boutique (données clients) : aucun accès Supabase.
