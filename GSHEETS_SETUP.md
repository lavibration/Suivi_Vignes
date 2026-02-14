# Configuration de la base de données Google Sheets

Cette application peut maintenant utiliser une Google Sheet comme base de données partagée, ce qui permet de conserver l'historique lors du partage ou du déploiement sur Streamlit Cloud.

## 1. Créer la Google Sheet
1. Créez une nouvelle Google Sheet nommée `Vignoble_Database`.
2. Créez les onglets suivants :
   - `traitements`
   - `vendanges`
   - `meteo`
   - `alertes`
   - `gdd`
   - `config`
   - `produits`
   - `fertilisation`

## 2. Configurer l'accès API
Il est recommandé d'utiliser une **Service Account** pour permettre à Streamlit d'écrire dans la feuille.

1. Allez sur la [Console Google Cloud](https://console.cloud.google.com/).
2. Créez un projet (si nécessaire).
3. Activez l'API **Google Sheets** et l'API **Google Drive**.
4. Créez un **Compte de service** (Service Account).
5. Générez une clé au format **JSON** pour ce compte de service.
6. **Important** : Partagez votre Google Sheet avec l'adresse e-mail du compte de service (en tant qu'Éditeur).

## 3. Configurer Streamlit (secrets.toml)
Dans votre dossier projet, créez ou modifiez le fichier `.streamlit/secrets.toml` :

```toml
[connections.gsheets]
spreadsheet = "https://docs.google.com/spreadsheets/d/VOTRE_ID_SHEET/edit"
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

Remplacez les valeurs par celles contenues dans votre fichier JSON de compte de service. Assurez-vous que la `private_key` contient les `\n` littéraux si nécessaire.

## 4. Structure des onglets (Référence)
L'application gère automatiquement la création des colonnes lors de la première sauvegarde, mais voici les colonnes principales utilisées :

### Onglet `traitements` (Registre Phytosanitaire)
- `parcelle`, `date`, `heure`, `culture`, `systeme_culture`, `produit`, `n_amm` (via `caracteristiques`), `dose_kg_ha`, `mouillage_pct`, `surface_traitee`, `type_utilisation`, `cible`, `conditions_meteo`, `applicateur`.

### Onglet `vendanges`
- `annee`, `type` (CAMPAGNE ou TICKET), et les métriques associées (poids, degré, etc.).

### Onglet `config`
- Une colonne `json_content` contenant toute la configuration technique.

## 5. Fonctionnement
Si les secrets sont configurés, l'application synchronisera automatiquement les données avec la Google Sheet. En l'absence de configuration, elle continuera d'utiliser les fichiers JSON locaux.
