# Azure TODO App

Application web TODO conteneurisée et déployée sur Microsoft Azure.

## Choix technologiques

| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.11 + Flask 3.0 |
| Base de données | Azure Cosmos DB (API MongoDB) + pymongo |
| Stockage objet | Azure Blob Storage + azure-storage-blob |
| Conteneur | Docker (python:3.11-slim) |
| Registre d'images | Azure Container Registry (ACR) |
| Hébergement | Azure App Service for Containers (Linux, B1) |
| Secrets | Azure Key Vault (Key Vault References) |
| Identité | Azure Managed Identity (System-assigned) |

## Architecture

```
Navigateur
    │  HTTP
    ▼
Azure App Service for Containers
  (todo-app:latest ← ACR)
    │
    ├─── Azure Cosmos DB (API MongoDB)
    │       database: tododb
    │       collection: tasks
    │
    ├─── Azure Key Vault
    │       secret: cosmos-connection-string
    │       accès via Managed Identity (Key Vault Reference)
    │
    └─── Azure Blob Storage
            container: exports
            export JSON des tâches à la demande
```

## Ressources Azure utilisées

| Ressource | Nom | Rôle |
|-----------|-----|------|
| Resource Group | `rg-todo` | Conteneur logique de toutes les ressources |
| Container Registry | `todoacr*` | Stockage de l'image Docker |
| Cosmos DB Account | `cosmos-todo-*` | Base de données MongoDB managée |
| Key Vault | `kv-todo-*` | Stockage sécurisé des secrets |
| Storage Account | `sttodo*` | Stockage objet (exports JSON) |
| App Service Plan | `asp-todo` | Plan d'hébergement Linux B1 |
| App Service | `app-todo-*` | Application web conteneurisée |
| Deployment Slot | `staging` | Environnement de pré-production |

## Principales commandes Azure CLI

```bash
# Connexion et groupe de ressources
az login
az group create --name rg-todo --location francecentral

# Azure Container Registry
az acr create --name $ACR_NAME --resource-group rg-todo --sku Basic --admin-enabled true
az acr login --name $ACR_NAME
docker build -t todo-app:latest .
docker tag todo-app:latest $ACR_LOGIN_SERVER/todo-app:latest
docker push $ACR_LOGIN_SERVER/todo-app:latest

# Cosmos DB
az cosmosdb create --name $COSMOS_ACCOUNT --resource-group rg-todo --kind MongoDB --server-version 4.2
az cosmosdb mongodb database create --account-name $COSMOS_ACCOUNT --resource-group rg-todo --name tododb
az cosmosdb mongodb collection create --account-name $COSMOS_ACCOUNT --resource-group rg-todo --database-name tododb --name tasks --shard "_id"
COSMOS_CONN=$(az cosmosdb keys list --name $COSMOS_ACCOUNT --resource-group rg-todo --type connection-strings --query "connectionStrings[0].connectionString" -o tsv)

# Key Vault + Managed Identity
az keyvault create --name $KEYVAULT_NAME --resource-group rg-todo
az keyvault secret set --vault-name $KEYVAULT_NAME --name cosmos-connection-string --value "$COSMOS_CONN"
az webapp identity assign --name $APP_NAME --resource-group rg-todo
PRINCIPAL_ID=$(az webapp identity show --name $APP_NAME --resource-group rg-todo --query principalId -o tsv)
az keyvault set-policy --name $KEYVAULT_NAME --object-id $PRINCIPAL_ID --secret-permissions get list
SECRET_URI=$(az keyvault secret show --vault-name $KEYVAULT_NAME --name cosmos-connection-string --query id -o tsv)
az webapp config appsettings set --name $APP_NAME --resource-group rg-todo --settings "COSMOS_CONNECTION_STRING=@Microsoft.KeyVault(SecretUri=$SECRET_URI)"

# App Service
az appservice plan create --name asp-todo --resource-group rg-todo --is-linux --sku B1
az webapp create --name $APP_NAME --resource-group rg-todo --plan asp-todo --deployment-container-image-name "$ACR_LOGIN_SERVER/todo-app:latest"
az webapp config appsettings set --name $APP_NAME --resource-group rg-todo --settings "WEBSITES_PORT=5000" "PORT=5000"

# Blob Storage
az storage account create --name $STORAGE_ACCOUNT --resource-group rg-todo --sku Standard_LRS --kind StorageV2
STORAGE_CONN=$(az storage account show-connection-string --name $STORAGE_ACCOUNT --resource-group rg-todo --query connectionString -o tsv)
az storage container create --name exports --connection-string "$STORAGE_CONN" --public-access blob
az webapp config appsettings set --name $APP_NAME --resource-group rg-todo --settings "STORAGE_CONNECTION_STRING=$STORAGE_CONN" "BLOB_CONTAINER=exports"

# Deployment slot
az webapp deployment slot create --name $APP_NAME --resource-group rg-todo --slot staging --configuration-source $APP_NAME

# Scaling
az appservice plan update --name asp-todo --resource-group rg-todo --number-of-workers 2
az appservice plan update --name asp-todo --resource-group rg-todo --number-of-workers 1
```

## URL de l'application

- **Production :** `https://<app-name>.azurewebsites.net`
- **Staging :** `https://<app-name>-staging.azurewebsites.net`

*(Remplacer `<app-name>` par la valeur réelle après déploiement)*

## Explication des services Azure

### Azure Cosmos DB
Stocke les tâches (titre, statut, date de création) dans une collection MongoDB. La persistance est démontrée en ajoutant des tâches depuis l'UI et en vérifiant leur présence dans le portail Azure (Data Explorer) après redémarrage du conteneur.

### Azure Key Vault + Managed Identity
La chaîne de connexion Cosmos DB est stockée comme secret dans Key Vault. L'App Service utilise une **Key Vault Reference** dans ses App Settings : `@Microsoft.KeyVault(SecretUri=...)`. Grâce à la **Managed Identity System-assigned**, App Service résout automatiquement la valeur au runtime sans stocker de secret dans le code ni dans le dépôt git.

### Azure Blob Storage
L'endpoint `POST /api/export` exporte toutes les tâches en JSON et les dépose dans le container `exports`. Chaque blob est accessible via URL publique. Une politique de cycle de vie supprime automatiquement les exports après 30 jours.

### Deployment Slots
Le slot `staging` permet de déployer et tester une nouvelle version de l'application sans impacter la production. Un **swap** (échange) entre slots se fait en quelques secondes sans interruption de service ni changement d'URL pour les utilisateurs. En cas de problème, le rollback est immédiat en re-swappant.

## Limites rencontrées

- Le plan **B1 ne supporte pas l'autoscaling** (scale automatique basé sur CPU/requêtes) — il faudrait passer à S1 ou supérieur. Le scaling manuel reste disponible.
- **Cosmos DB Free Tier** est limité à 400 RU/s partagés sur le compte. Suffisant pour une démo, mais insuffisant pour une charge réelle.
- La résolution des **Key Vault References** peut prendre quelques secondes au premier démarrage du conteneur.
- **Cold start** : App Service peut mettre quelques secondes à répondre après une période d'inactivité sur B1.
