import os
import json

class Franken2:
    IDENTITY = "Franken2"
    ROLE="load_balancing"
    PATH = os.path.dirname(__file__)
    IDENT_PATH = os.path.join(PATH, "ident.card")
    RESPONSIBILITY_PATH = os.path.join(PATH, "responsibility.json")

    def __init__(self):
        self.ident = self._load_ident()
        self.responsibility = self._load_responsibility()

    def _load_ident(self):
        try:
            with open(self.IDENT_PATH) as f:
                return f.read().strip()
        except:
            return self.IDENTITY

    def _load_responsibility(self):
        try:
            with open(self.OVERFLOW_PATH) as f:
                return json.load(f)
        except:
            return {}

    # --- existing logic ---
    def propose_route(self, ball):
        ball_type = ball.get("type", "default")
        routing_table = {
            "physics": "system_1",
            "ai": "system_2",
            "network": "system_3",
            "assets": "system_4",
        }
        target = routing_table.get(ball_type, "system_1")
        return {"target": target}

    def broadcast(self, ball):
        return {"peer": self.ident, "status": "ok"}

    def heartbeat(self):
        return {"peer": self.ident, "alive": True}

class Freewheeling:
    IDENTITY = "Freewheeling"
    ROLE="memory_bank"
    PATH = os.path.dirname(__file__)
    IDENT_PATH = os.path.join(PATH, "ident.card")
    RESPONSIBILITY_PATH = os.path.join(PATH, "responsibility.json")

    def store_warm(self, key, value): 
        self.warm_memory[key] = value
    def store_cold(self, key, value):
        self.cold_storage.write(key,value)
    def load_warm(self, ket):
        return self.warm_memory.get(key)
    def load_cold(self, key):
        return self.cold_storage.read(key)

    def __init__(self):
        self.ident = self._load_ident()
        self.responsibility = self._load_responsibility()

        self.load = {
            "system_1": 0,
            "system_2": 0,
            "system_3": 0,
            "system_4": 0,
        }
        self.threshold = 5

    def _load_ident(self):
        try:
            with open(self.IDENT_PATH) as f:
                return f.read().strip()
        except:
            return self.IDENTITY

    def _load_responsibility(self):
        try:
            with open(self.RESPONSIBILITY_PATH) as f:
                return json.load(f)
        except:
            return {"role": "load_balancing"}

    # --- existing logic ---
class Propcoms:
    IDENTITY = "Propcoms"
    ROLE = "ring_validator"

    def __init__(self):
        self.ident = self.IDENTITY
        self._alive = True
        self._last_tick = 0

        # The ring defines what targets are valid
        self.valid_targets = ["system_1", "system_2", "system_3"]

    # --- NEW: validation instead of adjust_route ---
    def validate(self, ball, contextual):
        # Freewheeling already decided if escalation is needed
        if contextual.get("escalate"):
            return {"escalate": True}

        target = contextual.get("target")

        # Ensure the target is valid for this ring
        if target not in self.valid_targets:
            return {"escalate": True}

        # Local ring-level validation only
        return {"validated": True, "target": target}

    # --- NEW: Propcoms is the ring heartbeat ---
    def tick(self, peer_a, peer_b):
        self._last_tick += 1
        return {"tick": self._last_tick}

    # --- NEW: ring alive state for the Hat ---
    def ring_alive(self):
        return self._alive

    # --- NEW: ring health snapshot ---
    def ring_status(self):
        return {
            "alive": self._alive,
            "last_tick": self._last_tick
        }

    # --- unchanged but simplified ---
    def broadcast(self, ball):
        return {"peer": self.ident, "status": "ok"}

    # --- peer-level heartbeat ---
    def heartbeat(self):
        return {
            "peer": self.ident,
            "alive": self._alive,
            "last_tick": self._last_tick
        }
