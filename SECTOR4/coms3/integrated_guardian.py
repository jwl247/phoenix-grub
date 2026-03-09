import os
import json
import hashlib
import re
from datetime import datetime, time
from pathlib import Path
import getpass
import socket

class InstallerGuardian:
    """The cute tag-along who knows everyone in every department"""
    def __init__(self, registry_file='installer_registry.json'):
        self.registry_file = registry_file
        self.registry = self.load_registry()
        self.conflicts = []
        self.suggestions = []
        print("👋 Installer Guardian initialized - I know everyone here!")
        
    def load_registry(self):
        """Load centralized config registry"""
        if Path(self.registry_file).exists():
            with open(self.registry_file, 'r') as f:
                return json.load(f)
        return {
            'configs': {},
            'ports': {},
            'paths': {},
            'services': {},
            'conflicts_log': [],
            'friendships': {}
        }
    
    def save_registry(self):
        with open(self.registry_file, 'w') as f:
            json.dump(self.registry, f, indent=2)
    
    def make_friends(self, service1, service2):
        """Register that two services are friends (work together)"""
        if service1 not in self.registry['friendships']:
            self.registry['friendships'][service1] = []
        if service2 not in self.registry['friendships']:
            self.registry['friendships'][service2] = []
        
        if service2 not in self.registry['friendships'][service1]:
            self.registry['friendships'][service1].append(service2)
        if service1 not in self.registry['friendships'][service2]:
            self.registry['friendships'][service2].append(service1)
        
        self.save_registry()
        print(f"💕 {service1} and {service2} are now friends!")
    
    def are_friends(self, service1, service2):
        """Check if two services are registered friends"""
        friends1 = self.registry['friendships'].get(service1, [])
        return service2 in friends1
    
    def scan_config_file(self, filepath):
        """Scan config file and extract key settings"""
        config_data = {
            'filepath': str(filepath),
            'filename': Path(filepath).name,
            'type': self.detect_config_type(filepath),
            'ports': [],
            'paths': [],
            'settings': {},
            'scanned': datetime.now().isoformat()
        }
        
        try:
            with open(filepath, 'r') as f:
                content = f.read()
                
            port_patterns = [
                r'[Pp]ort[:\s=]+(\d+)',
                r'Listen\s+(\d+)',
                r':(\d{2,5})',
                r'PORT[:\s=]+(\d+)'
            ]
            for pattern in port_patterns:
                matches = re.findall(pattern, content)
                config_data['ports'].extend([int(p) for p in matches if p.isdigit()])
            
            path_patterns = [
                r'[Pp]ath[:\s=]+"?([/\\][\w/\\.-]+)"?',
                r'DocumentRoot\s+"?([/\\][\w/\\.-]+)"?',
                r'root\s+"?([/\\][\w/\\.-]+)"?'
            ]
            for pattern in path_patterns:
                matches = re.findall(pattern, content)
                config_data['paths'].extend(matches)
            
            config_data['ports'] = list(set(config_data['ports']))
            config_data['paths'] = list(set(config_data['paths']))
            
        except Exception as e:
            config_data['error'] = str(e)
        
        return config_data
    
    def detect_config_type(self, filepath):
        """Detect what type of config file this is"""
        name = Path(filepath).name.lower()
        path_str = str(filepath).lower()
        
        if 'apache' in name or 'httpd' in name:
            return 'Apache'
        elif 'nginx' in name:
            return 'Nginx'
        elif 'php' in name:
            return 'PHP'
        elif 'mysql' in name or 'mariadb' in name:
            return 'MySQL/MariaDB'
        elif 'docker' in name:
            return 'Docker'
        elif '.env' in name:
            return 'Environment'
        elif 'wamp' in path_str:
            return 'WAMP'
        elif 'lamp' in path_str:
            return 'LAMP'
        elif 'helix' in path_str:
            return 'Helix'
        elif 'lifefirst' in path_str:
            return 'LifeFirst'
        elif 'ollama' in path_str:
            return 'Ollama'
        elif 'vosk' in path_str:
            return 'Vosk'
        else:
            return 'Generic'
    
    def register_config(self, filepath, service_name=None):
        """Register config file in centralized registry"""
        config_data = self.scan_config_file(filepath)
        config_hash = hashlib.sha256(str(filepath).encode()).hexdigest()
        
        self.registry['configs'][config_hash] = config_data
        
        for port in config_data['ports']:
            if port not in self.registry['ports']:
                self.registry['ports'][port] = []
            self.registry['ports'][port].append({
                'config': config_hash,
                'service': service_name or config_data['type'],
                'file': str(filepath)
            })
        
        for path in config_data['paths']:
            if path not in self.registry['paths']:
                self.registry['paths'][path] = []
            self.registry['paths'][path].append({
                'config': config_hash,
                'service': service_name or config_data['type'],
                'file': str(filepath)
            })
        
        conflicts = self.check_conflicts(config_hash)
        
        self.save_registry()
        
        print(f"✓ Registered: {config_data['filename']} ({config_data['type']})")
        print(f"  Ports: {config_data['ports']}")
        print(f"  Paths: {len(config_data['paths'])}")
        
        if conflicts:
            print(f"  ⚠️  Conflicts detected: {len(conflicts)}")
            for conflict in conflicts:
                services = conflict['services']
                if len(services) == 2 and self.are_friends(services[0], services[1]):
                    print(f"  💕 But they're friends, so it's probably OK!")
        
        return config_hash, conflicts
    
    def check_conflicts(self, config_hash):
        """Check for conflicts with existing configs"""
        conflicts = []
        config = self.registry['configs'][config_hash]
        
        for port in config['ports']:
            existing = self.registry['ports'].get(port, [])
            if len(existing) > 1:
                conflicts.append({
                    'type': 'port',
                    'value': port,
                    'services': [e['service'] for e in existing],
                    'files': [e['file'] for e in existing]
                })
        
        for path in config['paths']:
            existing = self.registry['paths'].get(path, [])
            if len(existing) > 1:
                conflicts.append({
                    'type': 'path',
                    'value': path,
                    'services': [e['service'] for e in existing],
                    'files': [e['file'] for e in existing]
                })
        
        return conflicts
    
    def suggest_alternatives(self, conflict):
        """Suggest alternative ports/paths for conflicts"""
        suggestions = []
        
        if conflict['type'] == 'port':
            port = conflict['value']
            for offset in [1, 10, 100, 1000]:
                alt_port = port + offset
                if alt_port not in self.registry['ports'] and alt_port < 65535:
                    suggestions.append({
                        'type': 'port',
                        'original': port,
                        'alternative': alt_port,
                        'reason': f'Port {port} + {offset}'
                    })
                    if len(suggestions) >= 3:
                        break
        
        elif conflict['type'] == 'path':
            path = conflict['value']
            base = Path(path)
            for i in range(1, 4):
                alt_path = f"{base.parent}/{base.stem}_{i}{base.suffix}"
                if alt_path not in self.registry['paths']:
                    suggestions.append({
                        'type': 'path',
                        'original': path,
                        'alternative': alt_path,
                        'reason': f'Numbered variant {i}'
                    })
        
        return suggestions
    
    def resolve_conflicts(self):
        """Present all conflicts and suggest alternatives"""
        all_conflicts = []
        
        for port, users in self.registry['ports'].items():
            if len(users) > 1:
                services = [u['service'] for u in users]
                are_friends = len(services) == 2 and self.are_friends(services[0], services[1])
                
                all_conflicts.append({
                    'type': 'port',
                    'value': port,
                    'services': services,
                    'files': [u['file'] for u in users],
                    'friends': are_friends
                })
        
        for path, users in self.registry['paths'].items():
            if len(users) > 1:
                services = [u['service'] for u in users]
                are_friends = len(services) == 2 and self.are_friends(services[0], services[1])
                
                all_conflicts.append({
                    'type': 'path',
                    'value': path,
                    'services': services,
                    'files': [u['file'] for u in users],
                    'friends': are_friends
                })
        
        if not all_conflicts:
            print("✓ No conflicts detected! Everyone's getting along!")
            return []
        
        print(f"\n{'='*70}")
        print(f"💕 INSTALLER GUARDIAN - Checking who's stepping on toes")
        print(f"{'='*70}\n")
        
        resolutions = []
        for i, conflict in enumerate(all_conflicts, 1):
            if conflict.get('friends', False):
                print(f"\nConflict #{i}: {conflict['type'].upper()} (But they're friends!)")
            else:
                print(f"\nConflict #{i}: {conflict['type'].upper()}")
            
            print(f"  Value: {conflict['value']}")
            print(f"  Services: {', '.join(conflict['services'])}")
            print(f"  Files affected:")
            for f in conflict['files']:
                print(f"    - {f}")
            
            if conflict.get('friends', False):
                print(f"  💕 These services are registered as friends - probably intentional!")
            
            suggestions = self.suggest_alternatives(conflict)
            if suggestions and not conflict.get('friends', False):
                print(f"\n  💡 Alternative methods:")
                for j, sug in enumerate(suggestions, 1):
                    print(f"    [{j}] Use {sug['alternative']} ({sug['reason']})")
                
                resolutions.append({
                    'conflict': conflict,
                    'suggestions': suggestions
                })
        
        return resolutions
    
    def auto_scan(self, directories=None):
        """Auto-scan common config locations"""
        if directories is None:
            directories = [
                '/etc/apache2',
                '/etc/nginx',
                '/etc/php',
                '/etc/mysql',
                '/var/www/html',
                '/lvm',
                'C:\\wamp64\\bin',
                'C:\\xampp',
                './config',
                './'
            ]
        
        configs_found = []
        
        for directory in directories:
            if not Path(directory).exists():
                continue
            
            print(f"🔍 Scanning: {directory}")
            
            for root, dirs, files in os.walk(directory):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if any(ext in file.lower() for ext in ['.conf', '.ini', '.cfg', '.env', 'config', '.py']):
                        filepath = Path(root) / file
                        try:
                            config_hash, conflicts = self.register_config(filepath)
                            configs_found.append(str(filepath))
                        except Exception as e:
                            pass
        
        print(f"\n✓ Scanned {len(configs_found)} config files")
        return configs_found
    
    def introduce_to_port_guardian(self, port_guardian):
        """Introduce self to Port Guardian and sync registries"""
        print(f"\n👋 Hi Port Guardian! I'm Installer Guardian!")
        print(f"   Let me help you track all these configs...")
        
        configs = self.auto_scan()
        
        for port, users in self.registry['ports'].items():
            for user in users:
                service = user['service']
                if service not in port_guardian.config.get('registered_services', {}):
                    if 'registered_services' not in port_guardian.config:
                        port_guardian.config['registered_services'] = {}
                    
                    port_guardian.config['registered_services'][service] = {
                        'ports': [port],
                        'config_file': user['file'],
                        'registered_by': 'installer_guardian',
                        'registered_at': datetime.now().isoformat()
                    }
        
        port_guardian.save_config()
        print(f"\n💕 Synced {len(self.registry['ports'])} ports with Port Guardian!")


class FileGuardian:
    """Port Guardian - The main security enforcer"""
    def __init__(self, config_file='file_guardian.json', instance_id='guardian_1'):
        self.config_file = config_file
        self.instance_id = instance_id
        self.shared_intel_file = 'guardian_shared_intel.json'
        self.config = self.load_config()
        self.access_log = []
        self.violations = []
        self.threat_score = {}
        self.auto_block_list = []
        self.approved_patterns = []
        self.load_shared_intel()
        self.system_alive = True
        self.in_failsafe = False
        
        self.installer = InstallerGuardian()
        print(f"\n🛡️  Port Guardian [{self.instance_id}] initialized")
        
        self.installer.introduce_to_port_guardian(self)
        
    def load_config(self):
        if Path(self.config_file).exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {
            'protected_paths': [],
            'allowed_users': [getpass.getuser()],
            'allowed_ips': ['127.0.0.1', socket.gethostbyname(socket.gethostname())],
            'allowed_hours': {'start': '06:00', 'end': '23:00'},
            'suspicious_patterns': ['.exe', '.bat', '.sh', '.dll'],
            'max_access_per_minute': 10,
            'alert_on_delete': True,
            'alert_on_copy': True,
            'lockdown_mode': False,
            'auto_block_threshold': 3,
            'threat_decay_minutes': 30,
            'proactive_mode': True,
            'mirror_attack': True,
            'mirror_multiplier': 3,
            'interactive_mode': True,
            'auto_approve_known': True,
            'peer_mode': True,
            'trust_levels': {},
            'bcm_mode': False,
            'log_only_violations': False,
            'mesh_network': True,
            'consensus_required': 2,
            'vote_on_threats': True,
            'component_registry': {},
            'require_component_auth': True,
            'autonomous_mode': True,
            'failsafe_lockdown': True,
            'heartbeat_timeout': 30,
            'last_system_heartbeat': None,
            'registered_services': {}
        }
    
    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def load_shared_intel(self):
        try:
            if Path(self.shared_intel_file).exists():
                with open(self.shared_intel_file, 'r') as f:
                    shared = json.load(f)
                    
                for blocked in shared.get('global_blocks', []):
                    if blocked not in self.auto_block_list:
                        votes = shared.get('block_votes', {}).get(blocked, [])
                        if len(votes) >= self.config.get('consensus_required', 2):
                            self.auto_block_list.append(blocked)
                
                for identifier, score_data in shared.get('global_threats', {}).items():
                    if identifier not in self.threat_score:
                        self.threat_score[identifier] = score_data
                    else:
                        all_scores = [score_data['score'], self.threat_score[identifier]['score']]
                        avg_score = sum(all_scores) / len(all_scores)
                        self.threat_score[identifier]['score'] = int(avg_score)
        except:
            pass
    
    def system_heartbeat(self):
        self.config['last_system_heartbeat'] = datetime.now().isoformat()
        self.save_config()
        self.system_alive = True
        if self.in_failsafe:
            self.in_failsafe = False
    
    def query(self, question):
        q = question.lower()
        
        if 'violation' in q or 'attack' in q:
            return {
                'status': 'success',
                'total_violations': len(self.violations),
                'recent': self.violations[-5:],
                'message': f"Found {len(self.violations)} violations"
            }
        
        if 'access' in q or 'log' in q:
            return {
                'status': 'success',
                'total_accesses': len(self.access_log),
                'recent': self.access_log[-10:],
                'message': f"Total accesses: {len(self.access_log)}"
            }
        
        if 'protected' in q:
            return {
                'status': 'success',
                'protected_files': self.config['protected_paths'],
                'count': len(self.config['protected_paths'])
            }
        
        if 'installer' in q or 'config' in q:
            return {
                'status': 'success',
                'configs': len(self.installer.registry['configs']),
                'ports': len(self.installer.registry['ports']),
                'paths': len(self.installer.registry['paths'])
            }
        
        return {'status': 'error', 'message': 'Query not recognized'}


if __name__ == "__main__":
    import sys
    
    instance_id = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 'guardian_1'
    if instance_id.startswith('guardian'):
        guardian = FileGuardian(instance_id=instance_id)
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    else:
        guardian = FileGuardian()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'daemon':
            print(f"🛡️  [{guardian.instance_id}] Starting in daemon mode...")
            print(f"   BCM Mode: {guardian.config.get('bcm_mode', False)}")
            print(f"   Press Ctrl+C to stop")
            
            import time
            try:
                while True:
                    guardian.installer.auto_scan()
                    conflicts = guardian.installer.resolve_conflicts()
                    if conflicts:
                        print(f"⚠️  {len(conflicts)} conflicts detected")
                    
                    guardian.system_heartbeat()
                    time.sleep(300)
            except KeyboardInterrupt:
                print(f"\n👋 [{guardian.instance_id}] Shutting down...")
                guardian.save_config()
        
        elif cmd == 'shutdown':
            print(f"👋 [{guardian.instance_id}] Shutdown signal received")
            guardian.save_config()
            guardian.installer.save_registry()
        
        elif cmd == 'heartbeat':
            guardian.system_heartbeat()
        
        elif cmd == 'status':
            print(f"\n🛡️  Port Guardian [{guardian.instance_id}] Status:")
            print(f"  System alive: {guardian.system_alive}")
            print(f"  Failsafe: {guardian.in_failsafe}")
            print(f"  BCM mode: {guardian.config.get('bcm_mode', False)}")
            print(f"\n👋 Installer Guardian:")
            print(f"  Configs: {len(guardian.installer.registry['configs'])}")
            print(f"  Ports: {len(guardian.installer.registry['ports'])}")
        
        elif cmd == 'installer':
            sub_cmd = sys.argv[2] if len(sys.argv) > 2 else 'help'
            
            if sub_cmd == 'scan':
                guardian.installer.auto_scan()
            
            elif sub_cmd == 'conflicts':
                guardian.installer.resolve_conflicts()
            
            elif sub_cmd == 'ports':
                print("🔌 Registered Ports:")
                for port, users in sorted(guardian.installer.registry['ports'].items()):
                    print(f"\n  Port {port}:")
                    for user in users:
                        print(f"    - {user['service']}")
        
        else:
            print("🛡️  Integrated Guardian")
            print("\nCommands:")
            print("  daemon      - Run in daemon mode")
            print("  status      - Show status")
            print("  heartbeat   - Send heartbeat")
            print("  installer scan  - Scan configs")
    else:
        print("🛡️  Integrated Guardian")
        print("Use 'python3 integrated_guardian.py help' for commands")
