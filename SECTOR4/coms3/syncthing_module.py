/**
 * ═══════════════════════════════════════════════════════════════
 * HeIX SYNCTHING DISTRIBUTION MODULE
 * ═══════════════════════════════════════════════════════════════
 * Integrated versioning, distribution, and sync system
 * Built directly into HeIX - no separate Syncthing setup needed
 * 
 * Features:
 * - Automatic code distribution to test nodes
 * - Version snapshots on every sync
 * - Rollback capabilities
 * - Coverage tracking
 * - Self-contained (manages its own Syncthing instance)
 * ═══════════════════════════════════════════════════════════════
 */

const { exec, spawn } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);
const fs = require('fs').promises;
const path = require('path');
const fetch = require('node-fetch');

class HeIXSync {
  constructor(config = {}) {
    this.version = '1.0.0';
    
    this.config = {
      // HeIX paths
      heixRoot: config.heixRoot || '/opt/heix',
      snapshotBase: config.snapshotBase || '/snapshots/heix-versions',
      logDir: config.logDir || '/var/log/heix',
      
      // Syncthing configuration
      syncthingHome: config.syncthingHome || '/opt/heix/.syncthing',
      syncthingPort: config.syncthingPort || 8384,
      syncthingApiKey: config.syncthingApiKey || this._generateApiKey(),
      
      // Node roles
      role: config.role || 'master', // 'master' or 'node'
      masterAddress: config.masterAddress || null, // For nodes
      
      // Sync settings
      autoSnapshot: config.autoSnapshot || true,
      maxSnapshots: config.maxSnapshots || 10,
      
      // Distribution
      nodes: config.nodes || [], // Array of node IDs
      
      ...config
    };

    this.state = {
      syncthingProcess: null,
      syncthingRunning: false,
      currentVersion: null,
      lastSync: null,
      connectedNodes: []
    };

    this._init();
  }

  async _init() {
    this._log('info', `
╔════════════════════════════════════════════════════════════╗
║           HeIX Sync & Distribution System                 ║
║              Role: ${this.config.role.toUpperCase().padEnd(42)} ║
╚════════════════════════════════════════════════════════════╝
    `);

    // Create directories
    await this._ensureDirectories();
    
    // Load current version
    await this._loadCurrentVersion();
    
    // Check if Syncthing is installed
    await this._ensureSyncthing();
    
    this._log('success', 'HeIX Sync initialized');
  }

  /**
   * ═══════════════════════════════════════════════════════════════
   * SYNCTHING MANAGEMENT
   * ═══════════════════════════════════════════════════════════════
   */

  async _ensureSyncthing() {
    try {
      await execPromise('which syncthing');
      this._log('success', 'Syncthing found');
    } catch (error) {
      this._log('warning', 'Syncthing not found, installing...');
      await this._installSyncthing();
    }
  }

  async _installSyncthing() {
    this._log('info', 'Installing Syncthing...');
    
    try {
      // Download and install Syncthing
      const commands = [
        'curl -s https://syncthing.net/release-key.txt | sudo apt-key add -',
        'echo "deb https://apt.syncthing.net/ syncthing stable" | sudo tee /etc/apt/sources.list.d/syncthing.list',
        'sudo apt update',
        'sudo apt install -y syncthing'
      ];

      for (const cmd of commands) {
        await execPromise(cmd);
      }

      this._log('success', 'Syncthing installed');
    } catch (error) {
      this._log('error', `Failed to install Syncthing: ${error.message}`);
      throw error;
    }
  }

  async startSyncthing() {
    if (this.state.syncthingRunning) {
      this._log('warning', 'Syncthing already running');
      return;
    }

    this._log('info', 'Starting Syncthing...');

    // Generate Syncthing config if doesn't exist
    await this._generateSyncthingConfig();

    // Start Syncthing process
    this.state.syncthingProcess = spawn('syncthing', [
      '-home', this.config.syncthingHome,
      '-no-browser',
      '-no-restart',
      '-logflags=3'
    ]);

    this.state.syncthingProcess.stdout.on('data', (data) => {
      this._log('debug', `[Syncthing] ${data.toString().trim()}`);
    });

    this.state.syncthingProcess.stderr.on('data', (data) => {
      this._log('debug', `[Syncthing] ${data.toString().trim()}`);
    });

    this.state.syncthingProcess.on('close', (code) => {
      this._log('warning', `Syncthing exited with code ${code}`);
      this.state.syncthingRunning = false;
    });

    // Wait for Syncthing to start
    await this._waitForSyncthing();

    this.state.syncthingRunning = true;
    this._log('success', `Syncthing running on port ${this.config.syncthingPort}`);

    // Configure folders
    await this._configureFolders();

    // Start watching for changes
    this._watchForSyncEvents();
  }

  async stopSyncthing() {
    if (!this.state.syncthingRunning || !this.state.syncthingProcess) {
      return;
    }

    this._log('info', 'Stopping Syncthing...');
    this.state.syncthingProcess.kill('SIGTERM');
    this.state.syncthingRunning = false;
  }

  async _waitForSyncthing() {
    const maxAttempts = 30;
    let attempts = 0;

    while (attempts < maxAttempts) {
      try {
        const response = await fetch(`http://localhost:${this.config.syncthingPort}/rest/system/status`, {
          headers: { 'X-API-Key': this.config.syncthingApiKey }
        });

        if (response.ok) {
          return;
        }
      } catch (error) {
        // Not ready yet
      }

      await new Promise(resolve => setTimeout(resolve, 1000));
      attempts++;
    }

    throw new Error('Syncthing failed to start');
  }

  async _generateSyncthingConfig() {
    const configPath = path.join(this.config.syncthingHome, 'config.xml');

    try {
      await fs.access(configPath);
      this._log('info', 'Syncthing config exists');
      return;
    } catch {
      // Config doesn't exist, create it
      this._log('info', 'Generating Syncthing config...');
      
      await fs.mkdir(this.config.syncthingHome, { recursive: true });

      const config = `<?xml version="1.0" encoding="UTF-8"?>
<configuration version="37">
    <gui enabled="true" tls="false">
        <address>127.0.0.1:${this.config.syncthingPort}</address>
        <apikey>${this.config.syncthingApiKey}</apikey>
        <theme>default</theme>
    </gui>
    <options>
        <listenAddress>default</listenAddress>
        <globalAnnounceEnabled>false</globalAnnounceEnabled>
        <localAnnounceEnabled>true</localAnnounceEnabled>
        <relaysEnabled>false</relaysEnabled>
        <natEnabled>false</natEnabled>
        <urAccepted>-1</urAccepted>
    </options>
</configuration>`;

      await fs.writeFile(configPath, config);
      this._log('success', 'Syncthing config generated');
    }
  }

  async _configureFolders() {
    const folderConfig = {
      id: 'heix-code',
      label: 'HeIX Code',
      path: this.config.heixRoot,
      type: this.config.role === 'master' ? 'sendonly' : 'receiveonly',
      rescanIntervalS: 60,
      fsWatcherEnabled: true,
      fsWatcherDelayS: 10
    };

    try {
      // Add folder via API
      await fetch(`http://localhost:${this.config.syncthingPort}/rest/config/folders/heix-code`, {
        method: 'PUT',
        headers: {
          'X-API-Key': this.config.syncthingApiKey,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(folderConfig)
      });

      this._log('success', 'HeIX folder configured');
    } catch (error) {
      this._log('error', `Failed to configure folder: ${error.message}`);
    }
  }

  /**
   * ═══════════════════════════════════════════════════════════════
   * NODE MANAGEMENT
   * ═══════════════════════════════════════════════════════════════
   */

  async addNode(nodeConfig) {
    const { deviceId, name, address } = nodeConfig;

    this._log('info', `Adding node: ${name} (${deviceId})`);

    const deviceConfig = {
      deviceID: deviceId,
      name: name,
      addresses: [address],
      compression: 'metadata',
      introducer: false,
      skipIntroductionRemovals: false,
      paused: false
    };

    try {
      await fetch(`http://localhost:${this.config.syncthingPort}/rest/config/devices/${deviceId}`, {
        method: 'PUT',
        headers: {
          'X-API-Key': this.config.syncthingApiKey,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(deviceConfig)
      });

      // Share folder with this device
      await this._shareFolderWithDevice(deviceId);

      this.config.nodes.push(deviceId);
      this._log('success', `Node added: ${name}`);
    } catch (error) {
      this._log('error', `Failed to add node: ${error.message}`);
    }
  }

  async _shareFolderWithDevice(deviceId) {
    try {
      // Get current folder config
      const response = await fetch(`http://localhost:${this.config.syncthingPort}/rest/config/folders/heix-code`, {
        headers: { 'X-API-Key': this.config.syncthingApiKey }
      });

      const folderConfig = await response.json();
      
      // Add device to folder
      if (!folderConfig.devices) {
        folderConfig.devices = [];
      }
      
      folderConfig.devices.push({
        deviceID: deviceId,
        introducedBy: ''
      });

      // Update folder config
      await fetch(`http://localhost:${this.config.syncthingPort}/rest/config/folders/heix-code`, {
        method: 'PUT',
        headers: {
          'X-API-Key': this.config.syncthingApiKey,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(folderConfig)
      });

      this._log('success', `Shared heix-code folder with device ${deviceId}`);
    } catch (error) {
      this._log('error', `Failed to share folder: ${error.message}`);
    }
  }

  async getConnectedNodes() {
    try {
      const response = await fetch(`http://localhost:${this.config.syncthingPort}/rest/system/connections`, {
        headers: { 'X-API-Key': this.config.syncthingApiKey }
      });

      const data = await response.json();
      const connections = Object.entries(data.connections || {})
        .filter(([id, conn]) => conn.connected)
        .map(([id, conn]) => ({
          id: id,
          address: conn.address,
          at: conn.at
        }));

      this.state.connectedNodes = connections;
      return connections;
    } catch (error) {
      this._log('error', `Failed to get connections: ${error.message}`);
      return [];
    }
  }

  /**
   * ═══════════════════════════════════════════════════════════════
   * VERSIONING & SNAPSHOTS
   * ═══════════════════════════════════════════════════════════════
   */

  async tagVersion(tag) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const version = `v-${tag}-${timestamp}`;

    this._log('info', `Tagging version: ${version}`);

    // Update VERSION file
    const versionFile = path.join(this.config.heixRoot, 'VERSION');
    await fs.writeFile(versionFile, version);

    this.state.currentVersion = version;

    // Create snapshot
    if (this.config.autoSnapshot) {
      await this.createSnapshot(version);
    }

    return version;
  }

  async createSnapshot(version = null) {
    if (!version) {
      version = this.state.currentVersion || 'manual-' + Date.now();
    }

    const snapshotPath = path.join(this.config.snapshotBase, `heix-${version}`);

    this._log('info', `Creating snapshot: ${version}`);

    try {
      // Create snapshot directory
      await fs.mkdir(this.config.snapshotBase, { recursive: true });

      // rsync the system
      const excludes = [
        '/dev/*', '/proc/*', '/sys/*', '/tmp/*', '/run/*',
        '/mnt/*', '/media/*', '/lost+found', '/snapshots/*'
      ].map(e => `--exclude="${e}"`).join(' ');

      const cmd = `rsync -aAXH ${excludes} / "${snapshotPath}/"`;
      await execPromise(cmd);

      // Save metadata
      const metadata = {
        version: version,
        timestamp: Date.now(),
        role: this.config.role,
        nodes: this.state.connectedNodes.length
      };

      await fs.writeFile(
        path.join(snapshotPath, 'HEIX_SNAPSHOT.json'),
        JSON.stringify(metadata, null, 2)
      );

      this._log('success', `Snapshot created: ${version}`);

      // Cleanup old snapshots
      await this._cleanupOldSnapshots();

      return snapshotPath;
    } catch (error) {
      this._log('error', `Snapshot failed: ${error.message}`);
      throw error;
    }
  }

  async listSnapshots() {
    try {
      const files = await fs.readdir(this.config.snapshotBase);
      const snapshots = [];

      for (const file of files) {
        if (file.startsWith('heix-')) {
          const metadataPath = path.join(this.config.snapshotBase, file, 'HEIX_SNAPSHOT.json');
          try {
            const metadata = JSON.parse(await fs.readFile(metadataPath, 'utf8'));
            snapshots.push({
              name: file,
              ...metadata
            });
          } catch {
            snapshots.push({ name: file, version: 'unknown' });
          }
        }
      }

      return snapshots.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
    } catch (error) {
      return [];
    }
  }

  async rollback(snapshotName) {
    const snapshotPath = path.join(this.config.snapshotBase, snapshotName);

    this._log('warning', `Rolling back to: ${snapshotName}`);

    try {
      // Verify snapshot exists
      await fs.access(snapshotPath);

      // Restore from snapshot
      const cmd = `rsync -aAXHv "${snapshotPath}/" /`;
      await execPromise(cmd);

      // Reload current version
      await this._loadCurrentVersion();

      this._log('success', `Rollback complete: ${snapshotName}`);
      this._log('warning', 'Reboot recommended');

      return true;
    } catch (error) {
      this._log('error', `Rollback failed: ${error.message}`);
      throw error;
    }
  }

  async _cleanupOldSnapshots() {
    const snapshots = await this.listSnapshots();
    
    if (snapshots.length > this.config.maxSnapshots) {
      const toDelete = snapshots.slice(this.config.maxSnapshots);
      
      for (const snapshot of toDelete) {
        const snapshotPath = path.join(this.config.snapshotBase, snapshot.name);
        try {
          await execPromise(`rm -rf "${snapshotPath}"`);
          this._log('info', `Deleted old snapshot: ${snapshot.name}`);
        } catch (error) {
          this._log('error', `Failed to delete snapshot: ${error.message}`);
        }
      }
    }
  }

  /**
   * ═══════════════════════════════════════════════════════════════
   * SYNC EVENT HANDLING
   * ═══════════════════════════════════════════════════════════════
   */

  _watchForSyncEvents() {
    // Poll for sync events
    this.syncEventInterval = setInterval(async () => {
      await this._checkForSyncCompletion();
    }, 5000);
  }

  async _checkForSyncCompletion() {
    try {
      const response = await fetch(`http://localhost:${this.config.syncthingPort}/rest/db/completion?folder=heix-code`, {
        headers: { 'X-API-Key': this.config.syncthingApiKey }
      });

      const data = await response.json();

      if (data.completion === 100 && this.state.lastSync !== data.globalBytes) {
        this.state.lastSync = data.globalBytes;
        await this._onSyncComplete();
      }
    } catch (error) {
      // Sync API not ready yet
    }
  }

  async _onSyncComplete() {
    this._log('success', 'Code synchronized');

    // Auto-snapshot if configured
    if (this.config.autoSnapshot && this.config.role === 'node') {
      await this._loadCurrentVersion();
      await this.createSnapshot(this.state.currentVersion);
    }

    // Emit event for other modules
    if (this.onSync) {
      this.onSync();
    }
  }

  /**
   * ═══════════════════════════════════════════════════════════════
   * UTILITIES
   * ═══════════════════════════════════════════════════════════════
   */

  async _ensureDirectories() {
    const dirs = [
      this.config.heixRoot,
      this.config.snapshotBase,
      this.config.logDir,
      this.config.syncthingHome
    ];

    for (const dir of dirs) {
      await fs.mkdir(dir, { recursive: true });
    }
  }

  async _loadCurrentVersion() {
    try {
      const versionFile = path.join(this.config.heixRoot, 'VERSION');
      this.state.currentVersion = (await fs.readFile(versionFile, 'utf8')).trim();
      this._log('info', `Current version: ${this.state.currentVersion}`);
    } catch {
      this.state.currentVersion = 'unknown';
    }
  }

  _generateApiKey() {
    return Array.from({ length: 32 }, () => 
      Math.floor(Math.random() * 16).toString(16)
    ).join('');
  }

  async getStatus() {
    const nodes = await this.getConnectedNodes();
    const snapshots = await this.listSnapshots();

    return {
      version: this.version,
      role: this.config.role,
      currentVersion: this.state.currentVersion,
      syncthingRunning: this.state.syncthingRunning,
      connectedNodes: nodes.length,
      totalSnapshots: snapshots.length,
      lastSync: this.state.lastSync ? new Date(this.state.lastSync) : null
    };
  }

  _log(level, message) {
    const timestamp = new Date().toISOString();
    const symbols = {
      info: '📘',
      success: '✅',
      warning: '⚠️',
      error: '❌',
      debug: '🔍',
      critical: '🚨'
    };
    console.log(`${timestamp} ${symbols[level] || '📝'} [HeIXSync] ${message}`);
  }
}

/**
 * ═══════════════════════════════════════════════════════════════
 * USAGE EXAMPLES
 * ═══════════════════════════════════════════════════════════════
 */

// Master node (development machine)
async function setupMaster() {
  const sync = new HeIXSync({
    role: 'master',
    heixRoot: '/opt/heix',
    snapshotBase: '/snapshots/heix-versions'
  });

  // Start Syncthing
  await sync.startSyncthing();

  // Tag initial version
  await sync.tagVersion('baseline');

  // Add test nodes
  await sync.addNode({
    deviceId: 'TEST-NODE-1-DEVICE-ID',
    name: 'test-node-1',
    address: 'tcp://192.168.1.101:22000'
  });

  // Check status
  const status = await sync.getStatus();
  console.log('Master Status:', status);

  return sync;
}

// Test node (receives code)
async function setupNode() {
  const sync = new HeIXSync({
    role: 'node',
    heixRoot: '/opt/heix',
    snapshotBase: '/snapshots/heix-versions',
    autoSnapshot: true, // Auto-snapshot on code updates
    masterAddress: '192.168.1.100'
  });

  // Start Syncthing
  await sync.startSyncthing();

  // Set up callback for when code syncs
  sync.onSync = async () => {
    console.log('🔄 New code received, snapshot created');
    
    // Optionally restart HeIX services
    // await restartHeIXServices();
  };

  return sync;
}

/**
 * ═══════════════════════════════════════════════════════════════
 * MODULE EXPORTS
 * ═══════════════════════════════════════════════════════════════
 */

module.exports = HeIXSync;
