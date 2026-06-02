"""
Aviator Game Data Capture Module
- a777bd.com login (RSA+DES encryption)
- Spribe SFS2X binary protocol decoder
- Real-time crash data via headless browser WebSocket interception
"""

import httpx
import json
import random
import base64
import uuid
import time
import asyncio
import struct
import zlib
import logging
from typing import Optional, Dict, List, Callable
from Crypto.Cipher import DES
from Crypto.Util.Padding import pad

logger = logging.getLogger("aviator")

SITE_CONFIG = {
    "base_url": "https://www.a777bd.com",
    "merchant": "777bdf2",
    "module_id": "COMM3",
    "gateway_version": "3",
    "language": "EN",
    "user_agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
}


def _js_rsa_encrypt(plaintext: str, modulus_hex: str, exponent_hex: str = "10001") -> str:
    mod = int(modulus_hex, 16)
    exp = int(exponent_hex, 16)
    mod_hex_len = len(modulus_hex)
    num_digits = (mod_hex_len // 2 + 1) // 2
    chunk_size = 2 * (num_digits - 1)
    data = list(plaintext.encode("utf-8"))
    while len(data) % chunk_size != 0:
        data.append(0)
    result = ""
    for i in range(0, len(data), chunk_size):
        num = 0
        digit_idx = 0
        a = i
        while a < i + chunk_size:
            lo = data[a] if a < len(data) else 0
            a += 1
            hi = data[a] if a < len(data) else 0
            a += 1
            num += (lo + (hi << 8)) << (16 * digit_idx)
            digit_idx += 1
        encrypted = pow(num, exp, mod)
        hex_str = format(encrypted, "x").zfill(mod_hex_len)
        result += hex_str
    return result


def _des_encrypt(plaintext: str, key: str) -> str:
    key_bytes = key.encode("utf-8")[:8]
    cipher = DES.new(key_bytes, DES.MODE_ECB)
    padded = pad(plaintext.encode("utf-8"), DES.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode()


def _random_string(length: int = 16) -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXTZabcdefghiklmnopqrstuvwxyz"
    return "".join(random.choice(chars) for _ in range(length))


class SFS2XDecoder:
    """Decodes SmartFoxServer 2X binary protocol messages"""

    @staticmethod
    def decode_value(data: bytes, offset: int):
        if offset >= len(data):
            return None, offset
        tid = data[offset]
        offset += 1
        if tid == 0:
            return None, offset
        elif tid == 1:
            return data[offset] != 0, offset + 1
        elif tid == 2:
            return data[offset], offset + 1
        elif tid == 3:
            return struct.unpack_from(">h", data, offset)[0], offset + 2
        elif tid == 4:
            return struct.unpack_from(">i", data, offset)[0], offset + 4
        elif tid == 5:
            return struct.unpack_from(">q", data, offset)[0], offset + 8
        elif tid == 6:
            return round(struct.unpack_from(">f", data, offset)[0], 6), offset + 4
        elif tid == 7:
            return round(struct.unpack_from(">d", data, offset)[0], 6), offset + 8
        elif tid == 8:
            sl = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return data[offset : offset + sl].decode("utf-8", "replace"), offset + sl
        elif tid == 18:
            return SFS2XDecoder.decode_object(data, offset)
        elif tid == 17:
            return SFS2XDecoder.decode_array(data, offset)
        elif tid == 10:
            al = struct.unpack_from(">i", data, offset)[0]
            offset += 4
            return list(data[offset : offset + al]), offset + al
        elif tid == 9:
            al = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return [data[offset + i] != 0 for i in range(al)], offset + al
        elif tid == 11:
            al = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return [struct.unpack_from(">h", data, offset + i * 2)[0] for i in range(al)], offset + al * 2
        elif tid == 12:
            al = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return [struct.unpack_from(">i", data, offset + i * 4)[0] for i in range(al)], offset + al * 4
        elif tid == 13:
            al = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return [struct.unpack_from(">q", data, offset + i * 8)[0] for i in range(al)], offset + al * 8
        elif tid == 14:
            al = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return [round(struct.unpack_from(">f", data, offset + i * 4)[0], 6) for i in range(al)], offset + al * 4
        elif tid == 15:
            al = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            return [round(struct.unpack_from(">d", data, offset + i * 8)[0], 6) for i in range(al)], offset + al * 8
        elif tid == 16:
            al = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            arr = []
            for _ in range(al):
                sl = struct.unpack_from(">H", data, offset)[0]
                offset += 2
                arr.append(data[offset : offset + sl].decode("utf-8", "replace"))
                offset += sl
            return arr, offset
        else:
            return f"<type_{tid}>", offset

    @staticmethod
    def decode_object(data: bytes, offset: int):
        nk = struct.unpack_from(">H", data, offset)[0]
        offset += 2
        obj = {}
        for _ in range(nk):
            kl = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            key = data[offset : offset + kl].decode("utf-8", "replace")
            offset += kl
            val, offset = SFS2XDecoder.decode_value(data, offset)
            obj[key] = val
        return obj, offset

    @staticmethod
    def decode_array(data: bytes, offset: int):
        al = struct.unpack_from(">H", data, offset)[0]
        offset += 2
        arr = []
        for _ in range(al):
            val, offset = SFS2XDecoder.decode_value(data, offset)
            arr.append(val)
        return arr, offset

    @staticmethod
    def decode_packet(raw: bytes) -> Optional[Dict]:
        if not raw or len(raw) < 4:
            return None
        header = raw[0]
        compressed = (header & 0x20) != 0
        size = struct.unpack_from(">H", raw, 1)[0]
        payload = raw[3:]
        if compressed:
            try:
                payload = zlib.decompress(payload)
            except Exception:
                return None
        try:
            if payload[0] == 18:
                obj, _ = SFS2XDecoder.decode_object(payload, 1)
                return obj
        except Exception:
            return None
        return None


class A777Session:
    """Manages authenticated session with a777bd.com"""

    def __init__(self, username: str, password: str, proxy: Optional[str] = None):
        self.username = username
        self.password = password
        self.proxy = proxy
        self.token: Optional[str] = None
        self.user_id: Optional[int] = None
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            kwargs = {
                "timeout": 20,
                "follow_redirects": True,
                "headers": {
                    "User-Agent": SITE_CONFIG["user_agent"],
                    "ModuleId": SITE_CONFIG["module_id"],
                    "X-Gateway-Version": SITE_CONFIG["gateway_version"],
                    "Merchant": SITE_CONFIG["merchant"],
                    "Language": SITE_CONFIG["language"],
                },
            }
            if self.proxy:
                kwargs["proxy"] = self.proxy
            self._client = httpx.Client(**kwargs)
        return self._client

    def login(self) -> bool:
        try:
            client = self._get_client()
            client.get(f"{SITE_CONFIG['base_url']}/m/home")
            rsa_key = client.get(
                f"{SITE_CONFIG['base_url']}/wps/session/key/rsa",
                headers={"Accept": "text/plain"},
            ).text.strip()
            des_key = _random_string(16)
            rsa_encrypted = _js_rsa_encrypt(des_key[::-1], rsa_key)
            login_data = {
                "username": self.username,
                "password": self.password,
                "captcha": "",
                "type": "1",
                "loginDeviceId": str(uuid.uuid4()),
                "isOfficialAppLogin": False,
            }
            json_str = json.dumps(login_data, separators=(",", ":"))
            des_encrypted = _des_encrypt(json_str, des_key)
            r = client.post(
                f"{SITE_CONFIG['base_url']}/wps/session/login",
                content=f'"{des_encrypted}"',
                headers={
                    "Content-Type": "application/json",
                    "Encryption": rsa_encrypted,
                    "Origin": SITE_CONFIG["base_url"],
                    "Referer": f"{SITE_CONFIG['base_url']}/m/home",
                },
            )
            resp = r.json()
            if resp.get("success"):
                self.token = resp["value"]["token"]
                self.user_id = resp["value"]["id"]
                logger.info(f"Login OK: {self.username} (id={self.user_id})")
                return True
            else:
                logger.error(f"Login failed: {resp.get('errorCode')} - {resp.get('message')}")
                return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def get_game_list(self) -> List[Dict]:
        if not self.token:
            return []
        client = self._get_client()
        r = client.get(
            f"{SITE_CONFIG['base_url']}/wps/relay/GCSGAME_gameList",
            params={"merchant": SITE_CONFIG["merchant"], "clientType": "3"},
            headers={"Authorization": self.token},
        )
        resp = r.json()
        if resp.get("success"):
            val = resp.get("value", {})
            return val.get("games", []) if isinstance(val, dict) else val
        return []

    def find_aviator(self) -> Optional[Dict]:
        games = self.get_game_list()
        for game in games:
            if isinstance(game, dict) and "aviator" in str(game.get("gameName", "")).lower():
                return game
        return None

    def launch_game(self, room_id: str) -> Optional[str]:
        if not self.token:
            return None
        client = self._get_client()
        r = client.get(
            f"{SITE_CONFIG['base_url']}/wps/game/launchGame",
            params={"roomId": room_id, "backUrl": f"{SITE_CONFIG['base_url']}/m/home"},
            headers={"Authorization": self.token, "ModuleId": "GAMELO3"},
        )
        resp = r.json()
        if resp.get("success"):
            return resp["value"].get("gameUrl")
        logger.warning(f"Game launch failed: {resp.get('errorCode')} - {resp.get('message')}")
        return None

    def close(self):
        if self._client:
            self._client.close()
            self._client = None


class AviatorDataCapture:
    """Captures real-time Aviator crash data via headless browser + SFS2X decode"""

    def __init__(self):
        self.crash_history: List[Dict] = []
        self.current_multiplier: float = 0.0
        self.current_round_id: Optional[int] = None
        self.game_state: str = "idle"
        self.online_players: int = 0
        self.on_crash: Optional[Callable] = None
        self.on_round_start: Optional[Callable] = None
        self.on_multiplier_update: Optional[Callable] = None
        self._running = False
        self._config: Optional[Dict] = None

    @staticmethod
    def get_demo_token() -> Optional[Dict]:
        try:
            r = httpx.get(
                "https://demo.spribe.io/launch/aviator",
                follow_redirects=False,
                headers={"User-Agent": SITE_CONFIG["user_agent"]},
                timeout=15,
            )
            if r.status_code == 302:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(r.headers["location"])
                params = parse_qs(parsed.query)
                return {
                    "token": params.get("token", [""])[0],
                    "user": params.get("user", [""])[0],
                    "operator": params.get("operator", ["demo"])[0],
                    "currency": params.get("currency", ["USD"])[0],
                    "lang": params.get("lang", ["EN"])[0],
                    "game_url": r.headers["location"],
                }
        except Exception as e:
            logger.error(f"Demo token error: {e}")
        return None

    @staticmethod
    def get_operator_config(operator: str = "demo") -> Optional[Dict]:
        try:
            r = httpx.get(
                f"https://app-config.spribegaming.com/aviator/{operator}.json",
                headers={"User-Agent": SITE_CONFIG["user_agent"]},
                timeout=15,
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.error(f"Config error: {e}")
        return None

    def _process_sfs_message(self, obj: Dict):
        p = obj.get("p", {})
        if not isinstance(p, dict):
            return

        ext_cmd = p.get("c", "")
        params = p.get("p", {})
        if not isinstance(params, dict):
            return

        if ext_cmd == "init":
            rounds_info = params.get("roundsInfo", [])
            if rounds_info:
                for ri in rounds_info:
                    if isinstance(ri, dict):
                        self._record_crash(
                            round_id=ri.get("roundId"),
                            multiplier=ri.get("maxMultiplier", 0),
                        )
                logger.info(f"Init: loaded {len(rounds_info)} round history")

        elif ext_cmd == "changeState":
            new_state = params.get("newStateId")
            round_id = params.get("roundId")

            if new_state == 1:
                self.game_state = "betting"
                self.current_round_id = round_id
                self.current_multiplier = 0.0
                if self.on_round_start:
                    self.on_round_start({"round_id": round_id, "state": "betting"})

            elif new_state == 2:
                self.game_state = "flying"
                self.current_round_id = round_id

        elif ext_cmd == "x":
            x = params.get("x")
            if x is not None:
                self.current_multiplier = float(x)
                if self.on_multiplier_update:
                    self.on_multiplier_update(self.current_multiplier)

        elif ext_cmd == "roundChartInfo":
            round_id = params.get("roundId")
            max_mult = params.get("maxMultiplier")
            if round_id and max_mult:
                self._record_crash(round_id=round_id, multiplier=max_mult)
                self.game_state = "crashed"
                logger.info(f"Round {round_id} crashed @ {max_mult}x")

        elif ext_cmd == "onlinePlayers":
            self.online_players = params.get("onlinePlayers", 0)

    def _record_crash(self, round_id, multiplier):
        if any(c["round_id"] == round_id for c in self.crash_history):
            return
        entry = {
            "round_id": round_id,
            "multiplier": float(multiplier),
            "timestamp": time.time(),
        }
        self.crash_history.append(entry)
        if len(self.crash_history) > 1000:
            self.crash_history = self.crash_history[-500:]
        if self.on_crash:
            self.on_crash(entry)

    async def capture_demo(self, duration: int = 300):
        """Capture live Aviator data from Spribe demo using headless browser"""
        from playwright.async_api import async_playwright

        self._running = True
        config = self.get_operator_config("demo")
        if not config:
            logger.error("Failed to get operator config")
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            ctx = await browser.new_context()
            page = await ctx.new_page()

            async def route_config(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    headers={"Access-Control-Allow-Origin": "*"},
                    body=json.dumps(config),
                )

            await page.route("**/app-config.spribegaming.com/aviator/demo.json*", route_config)

            def on_ws(ws):
                logger.info(f"WS connected: {ws.url[:80]}")

                def on_frame(payload):
                    if isinstance(payload, bytes):
                        obj = SFS2XDecoder.decode_packet(payload)
                        if obj:
                            self._process_sfs_message(obj)

                ws.on("framereceived", on_frame)

            page.on("websocket", on_ws)

            logger.info("Loading Spribe demo game...")
            await page.goto("https://demo.spribe.io/launch/aviator", timeout=45000)

            start = time.time()
            while self._running and (time.time() - start) < duration:
                await asyncio.sleep(1)

            await browser.close()
            logger.info(f"Capture ended. {len(self.crash_history)} crashes recorded")

    def stop(self):
        self._running = False

    def get_stats(self) -> Dict:
        if not self.crash_history:
            return {"count": 0, "status": self.game_state, "online": self.online_players}
        multipliers = [c["multiplier"] for c in self.crash_history]
        return {
            "count": len(multipliers),
            "avg": round(sum(multipliers) / len(multipliers), 2),
            "min": round(min(multipliers), 2),
            "max": round(max(multipliers), 2),
            "last_10": [round(m, 2) for m in multipliers[-10:]],
            "above_2x": sum(1 for m in multipliers if m >= 2.0),
            "above_5x": sum(1 for m in multipliers if m >= 5.0),
            "above_10x": sum(1 for m in multipliers if m >= 10.0),
            "status": self.game_state,
            "current_x": self.current_multiplier,
            "current_round": self.current_round_id,
            "online": self.online_players,
        }

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self.crash_history[-limit:]

    def predict_next(self) -> Dict:
        if len(self.crash_history) < 5:
            return {"confidence": 0, "message": "Not enough data yet (need 5+ rounds)"}

        mults = [c["multiplier"] for c in self.crash_history]
        recent = mults[-20:] if len(mults) >= 20 else mults
        last_5 = mults[-5:]

        avg_all = sum(mults) / len(mults)
        avg_recent = sum(recent) / len(recent)
        avg_last5 = sum(last_5) / len(last_5)

        low_streak = sum(1 for m in reversed(last_5) if m < 2.0)
        high_streak = sum(1 for m in reversed(last_5) if m >= 3.0)

        pct_below2 = sum(1 for m in recent if m < 2.0) / len(recent) * 100
        pct_2to5 = sum(1 for m in recent if 2.0 <= m < 5.0) / len(recent) * 100
        pct_5to10 = sum(1 for m in recent if 5.0 <= m < 10.0) / len(recent) * 100
        pct_above10 = sum(1 for m in recent if m >= 10.0) / len(recent) * 100

        base_pred = avg_recent * 0.6 + avg_all * 0.3 + avg_last5 * 0.1

        if low_streak >= 3:
            base_pred *= 1.4
            trend = "recovery"
            signal = "HIGH"
            confidence = min(75 + low_streak * 5, 92)
        elif low_streak >= 2:
            base_pred *= 1.2
            trend = "bounce"
            signal = "MEDIUM-HIGH"
            confidence = 68
        elif high_streak >= 3:
            base_pred *= 0.7
            trend = "correction"
            signal = "LOW"
            confidence = 65
        elif high_streak >= 2:
            base_pred *= 0.85
            trend = "cooling"
            signal = "MEDIUM-LOW"
            confidence = 60
        else:
            trend = "neutral"
            signal = "MEDIUM"
            confidence = 55

        last_crash = last_5[-1]
        if last_crash >= 20:
            base_pred *= 0.5
            trend = "post-moon"
            signal = "LOW"
            confidence = 70
        elif last_crash >= 10:
            base_pred *= 0.65
            trend = "post-spike"
            signal = "MEDIUM-LOW"
            confidence = 65
        elif last_crash <= 1.2:
            base_pred *= 1.3
            signal = "HIGH"
            confidence = min(confidence + 10, 90)

        pred = round(max(base_pred, 1.0), 2)

        if pred >= 5.0:
            range_low = round(pred * 0.4, 2)
            range_high = round(pred * 1.8, 2)
        elif pred >= 2.0:
            range_low = round(pred * 0.5, 2)
            range_high = round(pred * 2.0, 2)
        else:
            range_low = 1.0
            range_high = round(pred * 2.5, 2)

        if pred >= 5:
            advice = "High potential round - consider entering"
        elif pred >= 2:
            advice = "Moderate round expected - standard play"
        else:
            advice = "Low round likely - play safe or skip"

        return {
            "predicted_crash": pred,
            "range_low": range_low,
            "range_high": range_high,
            "confidence": confidence,
            "signal": signal,
            "trend": trend,
            "advice": advice,
            "last_5": [round(m, 2) for m in last_5],
            "avg_recent": round(avg_recent, 2),
            "avg_all": round(avg_all, 2),
            "low_streak": low_streak,
            "high_streak": high_streak,
            "distribution": {
                "below_2x": round(pct_below2, 1),
                "2x_5x": round(pct_2to5, 1),
                "5x_10x": round(pct_5to10, 1),
                "above_10x": round(pct_above10, 1),
            },
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    print("=== Aviator Data Capture Test ===\n")

    capture = AviatorDataCapture()

    def on_crash(entry):
        print(f"  CRASH: Round {entry['round_id']} @ {entry['multiplier']}x")

    def on_round_start(info):
        print(f"  NEW ROUND: {info['round_id']}")

    def on_mult(x):
        if x > 1 and (x * 100) % 50 == 0:
            print(f"  x = {x}")

    capture.on_crash = on_crash
    capture.on_round_start = on_round_start
    capture.on_multiplier_update = on_mult

    print("Starting 90s demo capture...")
    asyncio.run(capture.capture_demo(duration=90))

    print(f"\n=== Results ===")
    stats = capture.get_stats()
    print(json.dumps(stats, indent=2))
    print(f"\nLast 20 crashes:")
    for c in capture.get_history(20):
        print(f"  Round {c['round_id']}: {c['multiplier']}x")
