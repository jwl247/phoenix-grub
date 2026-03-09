# sync_engine.py

import os
import shutil
import time

class SyncEngine:
    def __init__(self, vars):
        self.vars = vars

    def _timestamp(self):
        return time.strftime("%Y%m%d_%H%M%S")

    def _ensure(self, path):
        os.makedirs(path, exist_ok=True)

    def sync(self, doorname, mode):
        """
        mode = "pilot", "system", or "system:d"
        """

        source = self.vars["sources"].get(doorname)
        if not source:
            return f"[SYNC] Unknown door '{doorname}'"

        # Resolve destinations
        destinations = []

        if mode == "pilot":
            destinations.append(self.vars["pilot"])
        elif mode == "system":
            destinations.append(self.vars["system"])
        elif mode == "system:d":
            destinations.append(self.vars["system"])
            destinations.append(self.vars["desktop"])
        else:
            return f"[SYNC] Unknown mode '{mode}'"

        # Warm → Hot → Egress
        warm = self.vars["warm"]
        hot = self.vars["hot"]

        self._ensure(warm)
        self._ensure(hot)

        warm_path = os.path.join(warm, f"{doorname}_warm_{self._timestamp()}")
        hot_path  = os.path.join(hot,  f"{doorname}_hot_{self._timestamp()}")

        # Stage warm
        shutil.copytree(source, warm_path)

        # Move to hot
        shutil.move(warm_path, hot_path)

        # Egress to destinations
        for dest in destinations:
            self._ensure(dest)
            out = os.path.join(dest, f"{doorname}_{self._timestamp()}")
            shutil.copytree(hot_path, out)

        # Cleanup hot
        shutil.rmtree(hot_path)

        return f"[SYNC] {doorname} → {mode} complete"
