@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Short name prefix for resources (letters/numbers only)')
param namePrefix string = 'fnol'

@description('Container image for all FNOL apps')
param containerImage string

@description('Foundry / Cognitive Services endpoint for Gemma 4 31B (set after model deploy)')
param foundryEndpoint string = ''

@description('Foundry deployment name')
param foundryDeployment string = 'gemma-4-31b'

@description('Enable optional AI summary (0 or 1)')
param aiEnabled string = '0'

@description('Entra object id for the Azure SQL Entra admin (user or group)')
param sqlAdminObjectId string

@description('Display login name for the Azure SQL Entra admin')
param sqlAdminLogin string = 'fnol-sql-admin'

var sqlServerName = '${namePrefix}-sql-${uniqueString(resourceGroup().id)}'
var sqlDbName = 'fnol'
var storageName = toLower(take('${namePrefix}st${uniqueString(resourceGroup().id)}', 24))
var envName = '${namePrefix}-env'
var logName = '${namePrefix}-logs'
var insightsName = '${namePrefix}-insights'
var kvName = take('${namePrefix}-kv-${uniqueString(resourceGroup().id)}', 24)
var contentSafetyName = '${namePrefix}-safety'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: insightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

var containers = [
  'case-documents'
  'policy-wording'
  'fnol-fixtures'
  'audit-archive'
]

resource blobContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = [for name in containers: {
  parent: blobServices
  name: name
  properties: {
    publicAccess: 'None'
  }
}]

resource sqlServer 'Microsoft.Sql/servers@2023-08-01' = {
  name: sqlServerName
  location: location
  properties: {
    administrators: {
      administratorType: 'ActiveDirectory'
      principalType: 'User'
      login: sqlAdminLogin
      sid: sqlAdminObjectId
      tenantId: subscription().tenantId
      azureADOnlyAuthentication: true
    }
  }
}

resource sqlDb 'Microsoft.Sql/servers/databases@2023-08-01' = {
  parent: sqlServer
  name: sqlDbName
  location: location
  sku: { name: 'Basic' }
}

resource contentSafety 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: contentSafetyName
  location: location
  kind: 'ContentSafety'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: contentSafetyName
    publicNetworkAccess: 'Enabled'
  }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

var sharedEnv = [
  { name: 'FNOL_SQL_SERVER', value: sqlServer.properties.fullyQualifiedDomainName }
  { name: 'FNOL_SQL_DATABASE', value: sqlDbName }
  { name: 'FNOL_BLOB_ACCOUNT', value: storage.name }
  { name: 'FNOL_DOCUMENTS_CONTAINER', value: 'case-documents' }
  { name: 'FNOL_POLICIES_CONTAINER', value: 'policy-wording' }
  { name: 'FNOL_FIXTURES_CONTAINER', value: 'fnol-fixtures' }
  { name: 'FNOL_STEP_TRANSPORT', value: 'http' }
  { name: 'FNOL_MODEL_PROVIDER', value: 'azure' }
  { name: 'FNOL_FOUNDRY_ENDPOINT', value: foundryEndpoint }
  { name: 'FNOL_FOUNDRY_DEPLOYMENT', value: foundryDeployment }
  { name: 'FNOL_CONTENT_SAFETY_ENDPOINT', value: contentSafety.properties.endpoint }
  { name: 'FNOL_AI_ENABLED', value: aiEnabled }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
]

resource enterprise 'Microsoft.App/containerApps@2023-05-01' = {
  name: '${namePrefix}-enterprise'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: false
        targetPort: 8767
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: 'enterprise'
          image: containerImage
          env: concat(sharedEnv, [
            { name: 'FNOL_MOCK_URL', value: 'http://localhost:8767' }
          ])
          command: [
            'uv'
            'run'
            '--locked'
            'python'
            'tools/runtime.py'
            'serve'
            '--host'
            '0.0.0.0'
            '--port'
            '8767'
          ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
}

var stepDefs = [
  { name: 'intake', script: 'server/input_server.py', port: 8080 }
  { name: 'policy', script: 'server/policy_server.py', port: 8080 }
  { name: 'rules', script: 'server/rules_server.py', port: 8080 }
  { name: 'citations', script: 'server/citation_server.py', port: 8080 }
]

resource stepApps 'Microsoft.App/containerApps@2023-05-01' = [for step in stepDefs: {
  name: '${namePrefix}-${step.name}'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: false
        targetPort: step.port
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: step.name
          image: containerImage
          env: concat(sharedEnv, [
            { name: 'FNOL_MOCK_URL', value: 'http://${namePrefix}-enterprise' }
            { name: 'FNOL_HTTP_PORT', value: string(step.port) }
          ])
          command: [
            'uv'
            'run'
            '--locked'
            'python'
            step.script
            '--http'
          ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}]

resource reviewer 'Microsoft.App/containerApps@2023-05-01' = {
  name: '${namePrefix}-reviewer'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8090
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: 'reviewer'
          image: containerImage
          env: concat(sharedEnv, [
            { name: 'FNOL_HTTP_PORT', value: '8090' }
            { name: 'FNOL_REVIEWER_REQUIRE_ROLE', value: '1' }
          ])
          command: [
            'uv'
            'run'
            '--locked'
            'python'
            'server/reviewer.py'
            '--host'
            '0.0.0.0'
            '--port'
            '8090'
          ]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
}

resource analystJob 'Microsoft.App/jobs@2023-05-01' = {
  name: '${namePrefix}-analyst'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    environmentId: containerEnv.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
    }
    template: {
      containers: [
        {
          name: 'analyst'
          image: containerImage
          env: concat(sharedEnv, [
            { name: 'FNOL_MOCK_URL', value: 'http://${namePrefix}-enterprise' }
            { name: 'FNOL_INTAKE_URL', value: 'http://${namePrefix}-intake' }
            { name: 'FNOL_POLICY_URL', value: 'http://${namePrefix}-policy' }
            { name: 'FNOL_RULES_URL', value: 'http://${namePrefix}-rules' }
            { name: 'FNOL_CITATIONS_URL', value: 'http://${namePrefix}-citations' }
          ])
          command: [
            'uv'
            'run'
            '--locked'
            'python'
            '-m'
            'fnol_analyst'
            'prepare'
            '--out'
            '/tmp/results.json'
          ]
          resources: { cpu: json('1.0'), memory: '2Gi' }
        }
      ]
    }
  }
}

output sqlFqdn string = sqlServer.properties.fullyQualifiedDomainName
output storageAccount string = storage.name
output reviewerFqdn string = reviewer.properties.configuration.ingress.fqdn
output contentSafetyEndpoint string = contentSafety.properties.endpoint
output keyVaultName string = keyVault.name
output appInsightsConnectionString string = appInsights.properties.ConnectionString
