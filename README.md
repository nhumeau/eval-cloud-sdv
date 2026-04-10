# Azure TODO App

Application web TODO conteneurisée et déployée sur Microsoft Azure, réalisée dans le cadre de l'évaluation pratique Cloud Azure.

## Choix technologiques

| Composant | Technologie | Justification |
|-----------|-------------|---------------|
| Backend | Python 3.11 + Flask 3.0 | Framework minimaliste, démarrage rapide, adapté aux APIs REST légères sans surcharge |
| Base de données | Azure Cosmos DB (API MongoDB) | Service managé, pas de serveur à gérer, API MongoDB compatible avec pymongo ; Free Tier suffisant pour la démo |
| ODM/driver | pymongo 4.7 | Driver officiel MongoDB, compatible avec l'API Cosmos DB sans adaptation |
| Stockage objet | Azure Blob Storage + azure-storage-blob | Service natif Azure, intégration directe via SDK Python, accès URL public sur les blobs |
| Conteneur | Docker (python:3.11-slim) | Image de base légère (~50 MB vs ~900 MB pour python:3.11), surface d'attaque réduite |
| Registre d'images | Azure Container Registry (SKU Standard) | Registre privé natif Azure, intégration directe avec App Service, authentification via admin ou Managed Identity |
| Hébergement | Azure App Service for Containers (Linux, S1) | PaaS managé, déploiement depuis ACR, support des Deployment Slots (S1 minimum requis) |
| Secrets | Azure Key Vault + Key Vault References | Aucun secret dans le code ni dans git ; résolution automatique par App Service via `@Microsoft.KeyVault(SecretUri=...)` |
| Identité | Managed Identity System-assigned | Zéro credentials à gérer : Azure attribue automatiquement une identité à l'App Service, révoquable sans rotation de clé |

## Architecture

```
Navigateur
    │  HTTPS
    ▼
Azure App Service for Containers  (app-todo-dev-0229.azurewebsites.net)
  image : acrtododev.azurecr.io/todo-app:latest
    │
    ├─── Azure Cosmos DB (API MongoDB)        cosmos-todo-dev-9589
    │       database  : tododb
    │       collection: tasks
    │       accès via chaîne de connexion injectée depuis Key Vault
    │
    ├─── Azure Key Vault                      kv-todo-0003
    │       secret : cosmos-connection-string
    │       secret : storage-connection-string
    │       accès via Managed Identity System-assigned (Key Vault Reference)
    │
    └─── Azure Blob Storage                   sttododev
            container : exports (accès public blob)
            export JSON des tâches à la demande (POST /api/export)
            lifecycle : Hot → Cool 30j → Archive 90j

Slot staging : app-todo-dev-0229-staging.azurewebsites.net
  même image ACR, configuration identique, identité propre
```

## Ressources Azure utilisées

| Ressource | Nom | Région | Rôle |
|-----------|-----|--------|------|
| Resource Group | `rg-todo-dev-swedencentral` | Sweden Central | Conteneur logique de toutes les ressources |
| Container Registry | `acrtododev` | Sweden Central | Stockage privé de l'image Docker (SKU Standard) |
| Cosmos DB Account | `cosmos-todo-dev-9589` | Sweden Central | Base de données MongoDB managée |
| Key Vault | `kv-todo-0003` | Sweden Central | Stockage sécurisé des secrets (RBAC) |
| Storage Account | `sttododev` | Sweden Central | Stockage objet — exports JSON (Standard_LRS) |
| App Service Plan | `asp-todo` | Sweden Central | Plan Linux S1 — supporte Deployment Slots |
| App Service | `app-todo-dev-0229` | Sweden Central | Application web conteneurisée |
| Deployment Slot | `staging` | — | Environnement de pré-production |

> **Région Sweden Central** : imposée par la politique de l'abonnement Azure for Students qui restreint les déploiements à un ensemble de régions autorisées (swedencentral, spaincentral, germanywestcentral, italynorth, uaenorth).

## Principales commandes Azure CLI utilisées

```bash
# Connexion et groupe de ressources
az login
az group create --name rg-todo-dev-swedencentral --location swedencentral

# Azure Container Registry
az acr create --name acrtododev --resource-group rg-todo-dev-swedencentral \
  --sku Standard --admin-enabled true
az acr login --name acrtododev
docker build -t todo-app:latest .
docker tag todo-app:latest acrtododev.azurecr.io/todo-app:latest
docker push acrtododev.azurecr.io/todo-app:latest
az acr repository show-tags --name acrtododev --repository todo-app -o table

# Cosmos DB (API MongoDB)
az cosmosdb create --name cosmos-todo-dev-9589 \
  --resource-group rg-todo-dev-swedencentral \
  --kind MongoDB --server-version 4.2 \
  --locations regionName=swedencentral failoverPriority=0
az cosmosdb mongodb database create \
  --account-name cosmos-todo-dev-9589 \
  --resource-group rg-todo-dev-swedencentral --name tododb
az cosmosdb mongodb collection create \
  --account-name cosmos-todo-dev-9589 \
  --resource-group rg-todo-dev-swedencentral \
  --database-name tododb --name tasks --shard "_id"
COSMOS_CONN=$(az cosmosdb keys list \
  --name cosmos-todo-dev-9589 \
  --resource-group rg-todo-dev-swedencentral \
  --type connection-strings \
  --query "connectionStrings[0].connectionString" -o tsv)

# Key Vault + Managed Identity
az keyvault create --name kv-todo-0003 \
  --resource-group rg-todo-dev-swedencentral --location swedencentral
az keyvault secret set --vault-name kv-todo-0003 \
  --name cosmos-connection-string --value "$COSMOS_CONN"
az webapp identity assign --name app-todo-dev-0229 \
  --resource-group rg-todo-dev-swedencentral
az role assignment create --role "Key Vault Secrets User" \
  --assignee <principalId> \
  --scope $(az keyvault show --name kv-todo-0003 --query id -o tsv)
SECRET_URI=$(az keyvault secret show --vault-name kv-todo-0003 \
  --name cosmos-connection-string --query id -o tsv)
az webapp config appsettings set --name app-todo-dev-0229 \
  --resource-group rg-todo-dev-swedencentral \
  --settings "COSMOS_CONNECTION_STRING=@Microsoft.KeyVault(SecretUri=$SECRET_URI)"

# App Service Plan + Web App
az appservice plan create --name asp-todo \
  --resource-group rg-todo-dev-swedencentral --is-linux --sku S1
az webapp create --name app-todo-dev-0229 \
  --resource-group rg-todo-dev-swedencentral \
  --plan asp-todo \
  --deployment-container-image-name acrtododev.azurecr.io/todo-app:latest

# Connexion App Service → ACR (credentials admin)
ACR_PWD=$(az acr credential show --name acrtododev --query "passwords[0].value" -o tsv)
az webapp config container set \
  --name app-todo-dev-0229 \
  --resource-group rg-todo-dev-swedencentral \
  --container-image-name acrtododev.azurecr.io/todo-app:latest \
  --container-registry-url https://acrtododev.azurecr.io \
  --container-registry-user acrtododev \
  --container-registry-password "$ACR_PWD"

# Blob Storage
az storage account create --name sttododev \
  --resource-group rg-todo-dev-swedencentral \
  --sku Standard_LRS --kind StorageV2 \
  --access-tier Hot --allow-blob-public-access true
az storage container create --name exports \
  --account-name sttododev --public-access blob

# Politique de cycle de vie (Hot → Cool 30j → Archive 90j)
az storage account management-policy create \
  --account-name sttododev \
  --resource-group rg-todo-dev-swedencentral \
  --policy @lifecycle-policy.json

# Deployment slot
az webapp deployment slot create --name app-todo-dev-0229 \
  --resource-group rg-todo-dev-swedencentral --slot staging

# Scaling manuel
az appservice plan update --name asp-todo \
  --resource-group rg-todo-dev-swedencentral --number-of-workers 2
az appservice plan update --name asp-todo \
  --resource-group rg-todo-dev-swedencentral --number-of-workers 1
```

## URL de l'application

- **Production :** https://app-todo-dev-0229.azurewebsites.net
- **Staging :** https://app-todo-dev-0229-staging.azurewebsites.net

## Explication des services Azure

### Azure Cosmos DB
Stocke les tâches (titre, statut, date de création) dans une collection MongoDB nommée `tasks`. La persistance est démontrée en ajoutant des tâches depuis l'interface web et en vérifiant leur présence dans le portail Azure (Data Explorer) après redémarrage du conteneur.

**Pourquoi MongoDB API ?** L'API MongoDB de Cosmos DB permet d'utiliser pymongo sans modification, tout en bénéficiant d'un service entièrement managé (réplication, backup, SLA) sans infrastructure à maintenir.

### Azure Key Vault + Managed Identity
La chaîne de connexion Cosmos DB et la chaîne de connexion Blob Storage sont stockées comme secrets dans Key Vault. L'App Service référence ces secrets via des **Key Vault References** dans ses App Settings : `@Microsoft.KeyVault(SecretUri=...)`. Grâce à la **Managed Identity System-assigned**, App Service résout automatiquement la valeur au runtime.

**Pourquoi cette approche ?** Aucun secret n'apparaît dans le code, dans les variables d'environnement en clair, ni dans le dépôt git. La rotation d'un secret dans Key Vault est immédiatement prise en compte sans redéploiement.

### Azure Blob Storage
L'endpoint `POST /api/export` exporte toutes les tâches en JSON et dépose le fichier dans le container `exports` sous la forme `export-YYYYMMDDTHHMMSS.json`. Chaque blob est accessible via URL publique. Une **politique de cycle de vie** est configurée : Hot → Cool après 30 jours → Archive après 90 jours, afin de réduire automatiquement les coûts de stockage sur les anciens exports.

**Pourquoi public ?** Pour permettre un accès direct par URL sans génération de SAS token, suffisant pour un export de données non sensibles.

### Deployment Slots
Le slot `staging` permet de déployer et tester une nouvelle version de l'application sans impacter la production. Un **swap** entre slots bascule le trafic en quelques secondes, sans changement d'URL pour les utilisateurs finaux. En cas de régression, le rollback est immédiat en re-swappant.

**Pourquoi S1 ?** Le plan B1 (Essentiel) ne supporte pas les Deployment Slots. S1 (Standard) est le tier minimum requis pour cette fonctionnalité.

### Scaling manuel
Le nombre d'instances du plan App Service peut être modifié à chaud sans interruption de service (`--number-of-workers`). En production, cela permet d'absorber des pics de charge en augmentant temporairement les instances, puis de réduire pour limiter les coûts.

## Utilisation de l'IA

L'IA (Claude) a été utilisée comme assistant tout au long du projet, sur trois axes principaux :

- **Frontend** : génération et amélioration de l'interface HTML/JS (design Fluent UI, barre de stats, filtres, affichage des dates de création et de résolution, gestion des états vides, export blob).
- **Backend** : aide à la structuration des routes Flask, gestion des erreurs (`InvalidId`, validation des entrées), ajout du champ `completed_at` lors de la résolution d'une tâche.
- **Documentation Azure / commandes CLI** : l'IA a servi de référence pour construire et corriger les commandes `az` (création ACR, Cosmos DB, Key Vault avec RBAC, App Service avec Key Vault References, politique de lifecycle Blob Storage, gestion des Deployment Slots). Elle a notamment permis d'identifier rapidement les causes d'erreurs Azure (provider non enregistré, noms globalement uniques, restrictions de région sur Azure for Students).
- **Rédaction** : aide à la rédaction de ce README (structure, justification des choix techniques, explication des services Azure).

## Limites rencontrées

- **Politique de région Azure for Students** : l'abonnement étudiant restreint les déploiements à 5 régions (swedencentral, spaincentral, germanywestcentral, italynorth, uaenorth). Switzerland North initialement prévue n'est pas autorisée.
- **Noms globalement uniques** : ACR, Cosmos DB, Key Vault et App Service ont des noms globaux — des suffixes numériques ont été ajoutés quand le nom souhaité était déjà pris.
- **Key Vault References et propagation RBAC** : après création du Key Vault en mode RBAC, l'attribution des rôles peut prendre quelques secondes à se propager avant que les secrets soient accessibles.
- **Cold start** : App Service peut mettre quelques secondes à répondre après une période d'inactivité (pas d'Always On sur S1 par défaut).
- **Autoscaling** : le scaling automatique basé sur CPU/requêtes nécessite un plan Premium. Le scaling manuel (modification du nombre d'instances) est disponible dès S1.
