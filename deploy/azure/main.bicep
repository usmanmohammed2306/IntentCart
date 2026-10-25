// Single-instance CPU host with local block storage for SQLite WAL.
// This template creates billable resources. Compile/what-if do not verify credit.
targetScope = 'resourceGroup'
@minLength(3)
@maxLength(20)
param prefix string = 'intentcart'
param location string = resourceGroup().location
@description('A reviewed CPU-only SKU. Check subscription quota and retail costs first.')
param vmSize string = 'Standard_B2pls_v2'
@description('Administrator public SSH key, not a private key or password.')
@minLength(32)
param sshPublicKey string
@description('One administrator IPv4 address without a suffix. The rule always appends /32.')
@minLength(7)
@maxLength(15)
param adminIpv4 string
param adminUsername string = 'intentcartadmin'
@description('A globally available DNS label in this Azure region.')
param dnsLabel string
var tags = { application: 'IntentCart', role: 'single-instance-cpu', funding: 'verify-credit-before-deploy' }
resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
 name: '${prefix}-nsg'
 location: location
 tags: tags
 properties: {
  securityRules: [
   { name: 'https', properties: { priority: 100, access: 'Allow', direction: 'Inbound', protocol: 'Tcp', sourcePortRange: '*', destinationPortRange: '443', sourceAddressPrefix: '*', destinationAddressPrefix: '*' } }
   { name: 'http-tls-redirect', properties: { priority: 110, access: 'Allow', direction: 'Inbound', protocol: 'Tcp', sourcePortRange: '*', destinationPortRange: '80', sourceAddressPrefix: '*', destinationAddressPrefix: '*' } }
   { name: 'admin-ssh', properties: { priority: 120, access: 'Allow', direction: 'Inbound', protocol: 'Tcp', sourcePortRange: '*', destinationPortRange: '22', sourceAddressPrefix: '${adminIpv4}/32', destinationAddressPrefix: '*' } }
  ]
 }
}
resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
 name: '${prefix}-network'
 location: location
 tags: tags
 properties: {
  addressSpace: { addressPrefixes: [ '10.20.0.0/16' ] }
  subnets: [ { name: 'app', properties: { addressPrefix: '10.20.0.0/24', networkSecurityGroup: { id: nsg.id } } } ]
 }
}
resource publicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
 name: '${prefix}-ip'
 location: location
 tags: tags
 sku: { name: 'Standard' }
 properties: { publicIPAllocationMethod: 'Static', dnsSettings: { domainNameLabel: dnsLabel } }
}
resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
 name: '${prefix}-nic'
 location: location
 tags: tags
 properties: {
  ipConfigurations: [ { name: 'primary', properties: { privateIPAllocationMethod: 'Dynamic', subnet: { id: '${network.id}/subnets/app' }, publicIPAddress: { id: publicIp.id } } } ]
 }
}
resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
 name: '${prefix}-host'
 location: location
 tags: tags
 properties: {
  hardwareProfile: { vmSize: vmSize }
  storageProfile: {
   imageReference: { publisher: 'Canonical', offer: 'ubuntu-24_04-lts', sku: 'server-arm64', version: 'latest' }
   osDisk: { createOption: 'FromImage', diskSizeGB: 32, managedDisk: { storageAccountType: 'StandardSSD_LRS' }, deleteOption: 'Delete' }
  }
  osProfile: {
   computerName: prefix
   adminUsername: adminUsername
   linuxConfiguration: { disablePasswordAuthentication: true, provisionVMAgent: true, ssh: { publicKeys: [ { path: '/home/${adminUsername}/.ssh/authorized_keys', keyData: sshPublicKey } ] } }
   customData: base64('''
#cloud-config
package_update: true
packages:
 - docker.io
 - docker-compose-v2
runcmd:
 - [systemctl, enable, --now, docker]
 - [mkdir, -p, /opt/intentcart]
''')
  }
  networkProfile: { networkInterfaces: [ { id: nic.id, properties: { primary: true, deleteOption: 'Delete' } } ] }
  diagnosticsProfile: { bootDiagnostics: { enabled: true } }
 }
}
output httpsOrigin string = 'https://${publicIp.properties.dnsSettings.fqdn}'
output vmResourceId string = vm.id
output deploymentScope string = 'Infrastructure only. Supply the audited linux/arm64 app image, private allocation, durable-volume marker and TLS proxy before launch.'
