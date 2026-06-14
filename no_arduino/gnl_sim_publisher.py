#!/usr/bin/env python3
"""
gnl_sim_publisher.py — Simulateur Arduino → MQTT (remplace arduino_serial_bridge.py)

Envoie exactement le même JSON que l'Arduino réel sur gnl/sim/raw :
  {"n1":82,"n2":34,"t1":22.3,"t2":-127,"p":1013.2,"g":145,"pump":0,"valve":0,"err":0}

Quand Arduino revient : remplacer par arduino_serial_bridge.py --port COM3
Aucun autre fichier à modifier.

Usage (Codespaces) :
  python gnl_sim_publisher.py
  python gnl_sim_publisher.py --host broker.hivemq.com --public
  python gnl_sim_publisher.py --scenario gas_leak   # tester fuite gaz
  python gnl_sim_publisher.py --scenario overflow    # tester débordement R2
  python gnl_sim_publisher.py --scenario sensor_fail # tester capteurs HS
"""

import argparse
import json
import logging
import math
import random
import time
import sys

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("gnl.sim")

SIM_TOPIC = "gnl/sim/raw"
INTERVAL  = 2.0  # secondes — même cadence que l'Arduino (toutes les 2s)


# ══════════════════════════════════════════════════════════════════════════════
# Physique réaliste — identique à ArduinoSimulator dans start_gnl_windows.py
# ══════════════════════════════════════════════════════════════════════════════

class ArduinoPhysics:
    """
    Reproduit le firmware gnl_main.ino :
    - Pompe : ON si R1 >= 80%, OFF si R1 < 20%
    - Vanne : OPEN si R2 >= 95%, CLOSE si R2 < 70%
    - Bitmask err : bit0=HC-SR04 R1, bit1=HC-SR04 R2, bit2=DS18B20, bit4=BMP280
    """

    def __init__(self, scenario: str = "normal"):
        self._t       = 0
        self.n1       = 78.0   # niveau R1 (%)
        self.n2       = 22.0   # niveau R2 (%)
        self.pump     = 0
        self.valve    = 0
        self.scenario = scenario

        # Variables internes scénarios
        self._gas_spike     = False
        self._gas_spike_cnt = 0
        self._scenario_step = 0

        log.info("Simulateur démarré — scénario : %s", scenario)
        if scenario != "normal":
            log.info("  → Scénario spécial activé en %ds", 20)

    def receive_command(self, cmd: str):
        """Réception commandes depuis gnl_main.py (via MQTT gnl/cmd/*)."""
        if   cmd == "CMD:PUMP_ON":     self.pump  = 1
        elif cmd == "CMD:PUMP_OFF":    self.pump  = 0
        elif cmd == "CMD:VALVE_OPEN":  self.valve = 1
        elif cmd == "CMD:VALVE_CLOSE": self.valve = 0
        elif cmd == "CMD:ESD":
            self.pump = 0; self.valve = 0
            log.warning("ESD reçu — pompe+vanne OFF")

    def read(self) -> dict:
        self._t += 1
        dt = INTERVAL

        # ── Physique niveaux (firmware Arduino) ──────────────────────────────
        if self.pump and self.n1 > 10:
            self.n1 -= 0.15 * dt + random.gauss(0, 0.03)
        if self.pump and self.n2 < 100:
            self.n2 += 0.12 * dt + random.gauss(0, 0.03)
        if self.n1 < 30:
            self.n1 += 0.08 * dt   # alimentation externe lente

        # ── Logique firmware Arduino ─────────────────────────────────────────
        if self.n2 >= 95:
            self.valve = 1
        elif self.n2 < 70:
            self.valve = 0

        if self.valve or self.n2 >= 95:
            self.pump = 0
        elif self.n1 >= 80:
            self.pump = 1
        elif self.n1 < 20:
            self.pump = 0

        self.n1 = max(5.0, min(100.0, self.n1))
        self.n2 = max(0.0, min(100.0, self.n2))

        # ── Capteurs ─────────────────────────────────────────────────────────
        t1  = 21.5 + 1.8 * math.sin(self._t / 25.0) + random.gauss(0, 0.08)
        p   = 1013.25 + 0.8 * math.sin(self._t / 60.0) + random.gauss(0, 0.3)
        g   = self._compute_gas()
        err = self._compute_err()

        return {
            "n1":    round(self.n1, 1),
            "n2":    round(self.n2, 1),
            "t1":    round(t1, 1),
            "t2":    -127,          # 1 seul DS18B20 comme dans le vrai Arduino
            "p":     round(p, 1),
            "g":     g,
            "pump":  self.pump,
            "valve": self.valve,
            "err":   err,
        }

    def _compute_gas(self) -> int:
        # Scénario fuite gaz
        if self.scenario == "gas_leak" and self._t > 10:
            self._scenario_step += 1
            return min(520, 80 + self._scenario_step * 8)

        # Pics aléatoires réalistes (0.4% de chance)
        if random.random() < 0.004:
            self._gas_spike = True
            self._gas_spike_cnt = random.randint(3, 8)

        if self._gas_spike:
            self._gas_spike_cnt -= 1
            if self._gas_spike_cnt <= 0:
                self._gas_spike = False
            return random.randint(270, 480)

        # Valeur normale
        g = int(115 + 18 * math.sin(self._t / 40.0) + random.gauss(0, 12))
        return max(70, min(210, g))

    def _compute_err(self) -> int:
        err = 0

        # Scénario capteurs HS : bit0+bit1 (HC-SR04 R1+R2) après 20s
        if self.scenario == "sensor_fail" and self._t > 10:
            err |= 0x03  # bit0=R1 HS, bit1=R2 HS

        # Scénario débordement : forcer R2 à monter vite
        if self.scenario == "overflow" and self._t > 10:
            self.n2 = min(100, self.n2 + 0.5)
            self.pump = 1

        return err


# ══════════════════════════════════════════════════════════════════════════════
# Client MQTT
# ══════════════════════════════════════════════════════════════════════════════

def build_client(args: argparse.Namespace) -> mqtt.Client:
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connecté → %s:%d", args.host, args.mqtt_port)
            # Écouter les commandes pour les répercuter sur le simulateur
            client.subscribe("gnl/cmd/#", qos=1)
        else:
            log.error("MQTT connexion refusée (rc=%d)", rc)

    def on_disconnect(client, userdata, rc):
        if rc != 0:
            log.warning("MQTT déconnecté (rc=%d) — reconnexion auto…", rc)

    def on_message(client, userdata, msg):
        """Commandes IA/dashboard → simulateur (boucle fermée)."""
        try:
            payload = json.loads(msg.payload.decode())
            cmd = payload.get("cmd") or msg.payload.decode().strip()
            userdata["physics"].receive_command(cmd)
            log.info("← Commande reçue [%s] : %s", msg.topic, cmd)
        except Exception:
            pass

    physics = ArduinoPhysics(scenario=args.scenario)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
        client_id="gnl_arduino_sim",
        clean_session=True,
        userdata={"physics": physics},
    )
    if not args.public:
        client.username_pw_set(args.user, args.password)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client, physics


def run(args: argparse.Namespace) -> None:
    client, physics = build_client(args)

    log.info("Connexion MQTT → %s:%d …", args.host, args.mqtt_port)
    client.connect(args.host, args.mqtt_port, keepalive=60)
    client.loop_start()
    time.sleep(1.0)  # attendre on_connect

    log.info("Publication sur topic '%s' toutes les %.1fs", SIM_TOPIC, INTERVAL)
    log.info("Ctrl+C pour arrêter")
    log.info("─" * 55)

    t_next = time.time()
    try:
        while True:
            now = time.time()
            if now >= t_next:
                data    = physics.read()
                payload = json.dumps(data)
                result  = client.publish(SIM_TOPIC, payload, qos=0)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    log.info(
                        "→ n1=%4.1f%% n2=%4.1f%% g=%-3d pump=%d valve=%d err=0x%02X",
                        data["n1"], data["n2"], data["g"],
                        data["pump"], data["valve"], data["err"],
                    )
                else:
                    log.warning("Échec publication (rc=%d)", result.rc)
                t_next += INTERVAL
            time.sleep(0.05)

    except KeyboardInterrupt:
        log.info("Arrêt demandé")
    finally:
        client.loop_stop()
        client.disconnect()
        log.info("Simulateur arrêté proprement")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Simulateur Arduino → MQTT (remplace arduino_serial_bridge.py)"
    )
    p.add_argument("--host",      default="broker.hivemq.com",
                   help="Hôte MQTT (défaut: broker.hivemq.com)")
    p.add_argument("--mqtt-port", type=int, default=1883,
                   help="Port MQTT (défaut: 1883)")
    p.add_argument("--user",      default="nouar",  help="Utilisateur MQTT")
    p.add_argument("--password",  default="hamel",  help="Mot de passe MQTT")
    p.add_argument("--public",    action="store_true",
                   help="MQTT sans authentification (broker.hivemq.com)")
    p.add_argument("--scenario",
                   choices=["normal", "gas_leak", "overflow", "sensor_fail"],
                   default="normal",
                   help=(
                       "normal      : fonctionnement nominal\n"
                       "gas_leak    : fuite méthane progressive (teste ESD)\n"
                       "overflow    : R2 monte vite (teste vanne+pompe)\n"
                       "sensor_fail : HC-SR04 R1+R2 tombent en panne (teste err bitmask)"
                   ))
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
