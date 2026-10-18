"""Small, pairing-code-protected TCP relay for local keyboard and mouse input."""

from __future__ import annotations

import hmac
import json
import secrets
import socket
import threading
from collections.abc import Iterator
from typing import Any

PORT = 8765
MAX_LINE_BYTES = 4096
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_MOUSE_DELTA = 2000
MAX_SCROLL_DELTA = 10


def new_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))


def local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))
        return probe.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        probe.close()


def _read_line(connection: socket.socket) -> bytes:
    result = bytearray()
    while len(result) <= MAX_LINE_BYTES:
        byte = connection.recv(1)
        if not byte:
            raise ConnectionError("Connection closed")
        if byte == b"\n":
            return bytes(result)
        result.extend(byte)
    raise ValueError("Message is too large")


def _read_messages(
    connection: socket.socket, stopped: threading.Event
) -> Iterator[dict[str, Any]]:
    buffer = bytearray()
    while not stopped.is_set():
        try:
            chunk = connection.recv(4096)
        except TimeoutError:
            continue
        if not chunk:
            return
        buffer.extend(chunk)
        if len(buffer) > MAX_LINE_BYTES and b"\n" not in buffer:
            raise ValueError("Message is too large")
        while b"\n" in buffer:
            line, _, remainder = buffer.partition(b"\n")
            buffer = bytearray(remainder)
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("Message is too large")
            packet = json.loads(line)
            if not isinstance(packet, dict):
                raise ValueError("Invalid event")
            yield packet


def _validate_event(packet: dict[str, Any]) -> dict[str, Any] | None:
    event_type = packet.get("type")
    if event_type in ("key_down", "key_up"):
        key = packet.get("key")
        if not isinstance(key, dict) or key.get("kind") not in ("char", "special"):
            return None
        value = key.get("value")
        if not isinstance(value, str) or len(value) > 16:
            return None
        if key["kind"] == "char" and (len(value) != 1 or not value.isprintable()):
            return None
        if key["kind"] == "special" and not value.isidentifier():
            return None
        return {"type": event_type, "key": {"kind": key["kind"], "value": value}}

    if event_type == "move":
        dx, dy = packet.get("dx"), packet.get("dy")
        if all(type(value) is int for value in (dx, dy)) and all(
            abs(value) <= MAX_MOUSE_DELTA for value in (dx, dy)
        ):
            return {"type": event_type, "dx": dx, "dy": dy}

    if event_type in ("button_down", "button_up"):
        button = packet.get("button")
        if button in ("left", "right", "middle"):
            return {"type": event_type, "button": button}

    if event_type == "scroll":
        dx, dy = packet.get("dx"), packet.get("dy")
        if all(type(value) is int for value in (dx, dy)) and all(
            abs(value) <= MAX_SCROLL_DELTA for value in (dx, dy)
        ):
            return {"type": event_type, "dx": dx, "dy": dy}

    return None


class InputReceiver:
    def __init__(self, code: str, host: str = "0.0.0.0", port: int = PORT) -> None:
        self.code = code
        self.host = host
        self.port = port
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._server: socket.socket | None = None
        self._client: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._status = "Stopped"

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def _set_status(self, value: str) -> None:
        with self._lock:
            self._status = value

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopped.clear()
        self._set_status("Starting")
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        for connection in (self._client, self._server):
            if connection:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        self._set_status("Stopped")

    def _serve(self) -> None:
        try:
            from pynput.keyboard import Controller as KeyboardController
            from pynput.mouse import Button, Controller as MouseController

            keyboard = KeyboardController()
            mouse = MouseController()
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server = server
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            server.settimeout(0.5)
            self._set_status(f"Waiting on port {self.port}")

            while not self._stopped.is_set():
                try:
                    client, _ = server.accept()
                except TimeoutError:
                    continue
                self._client = client
                client.settimeout(0.5)
                pressed_keys: dict[tuple[str, str], Any] = {}
                pressed_buttons: dict[str, Any] = {}
                try:
                    auth = json.loads(_read_line(client))
                    authorized = (
                        isinstance(auth, dict)
                        and isinstance(auth.get("code"), str)
                        and hmac.compare_digest(auth["code"], self.code)
                    )
                    client.sendall(
                        (json.dumps({"ok": authorized}) + "\n").encode())
                    if not authorized:
                        continue

                    self._set_status("Connected")
                    from pynput.keyboard import Key

                    for packet in _read_messages(client, self._stopped):
                        event = _validate_event(packet)
                        if event is None:
                            continue
                        event_type = event["type"]
                        if event_type in ("key_down", "key_up"):
                            key_data = event["key"]
                            identity = (key_data["kind"], key_data["value"])
                            if key_data["kind"] == "char":
                                key = key_data["value"]
                            else:
                                key = getattr(Key, key_data["value"], None)
                                if key is None:
                                    continue
                            if event_type == "key_down":
                                keyboard.press(key)
                                pressed_keys[identity] = key
                            elif identity in pressed_keys:
                                keyboard.release(pressed_keys.pop(identity))
                        elif event_type == "move":
                            mouse.move(event["dx"], event["dy"])
                        elif event_type in ("button_down", "button_up"):
                            button = getattr(Button, event["button"])
                            if event_type == "button_down":
                                mouse.press(button)
                                pressed_buttons[event["button"]] = button
                            elif event["button"] in pressed_buttons:
                                mouse.release(
                                    pressed_buttons.pop(event["button"]))
                        elif event_type == "scroll":
                            mouse.scroll(event["dx"], event["dy"])
                except (ConnectionError, OSError, TimeoutError, ValueError):
                    pass
                finally:
                    for key in pressed_keys.values():
                        try:
                            keyboard.release(key)
                        except Exception:
                            pass
                    for button in pressed_buttons.values():
                        try:
                            mouse.release(button)
                        except Exception:
                            pass
                    client.close()
                    self._client = None
                    if not self._stopped.is_set():
                        self._set_status(f"Waiting on port {self.port}")
        except Exception as error:
            self._set_status(f"Error: {error}")
        finally:
            if self._server:
                self._server.close()
                self._server = None
            if self._stopped.is_set():
                self._set_status("Stopped")


class InputController:
    def __init__(self) -> None:
        self._socket: socket.socket | None = None
        self._keyboard_listener: Any = None
        self._mouse_listener: Any = None
        self._send_lock = threading.Lock()
        self._position: tuple[int, int] | None = None
        self._position_lock = threading.Lock()
        self._stopped = threading.Event()
        self._status = "Stopped"
        self._status_lock = threading.Lock()

    @property
    def status(self) -> str:
        with self._status_lock:
            return self._status

    def _set_status(self, value: str) -> None:
        with self._status_lock:
            self._status = value

    def connect(self, host: str, code: str, port: int = PORT) -> None:
        if self._socket:
            raise RuntimeError("Sharing is already active")
        from pynput import keyboard, mouse

        connection = socket.create_connection((host, port), timeout=3)
        connection.settimeout(3)
        connection.sendall((json.dumps({"code": code}) + "\n").encode())
        response = json.loads(_read_line(connection))
        if not isinstance(response, dict) or response.get("ok") is not True:
            connection.close()
            raise PermissionError("Pairing code was not accepted")
        connection.settimeout(None)
        self._socket = connection
        self._stopped.clear()
        self._set_status("Sharing input")
        self._stop_chord_keys: set[str] = set()

        def send(packet: dict[str, Any]) -> None:
            if self._stopped.is_set() or not self._socket:
                return
            try:
                line = json.dumps(packet, separators=(",", ":")) + "\n"
                with self._send_lock:
                    self._socket.sendall(line.encode())
            except OSError:
                self.stop()

        def encode_key(key: Any) -> dict[str, str] | None:
            if getattr(key, "char", None) is not None:
                return {"kind": "char", "value": key.char}
            name = getattr(key, "name", None)
            if isinstance(name, str):
                return {"kind": "special", "value": name}
            return None

        def on_press(key: Any) -> None:
            name = getattr(key, "name", None)
            if name in ("ctrl", "ctrl_l", "ctrl_r"):
                self._stop_chord_keys.add("ctrl")
            elif name in ("alt", "alt_l", "alt_r"):
                self._stop_chord_keys.add("alt")
            encoded = encode_key(key)
            if encoded:
                send({"type": "key_down", "key": encoded})

        def on_release(key: Any) -> bool | None:
            encoded = encode_key(key)
            if encoded:
                send({"type": "key_up", "key": encoded})
            name = getattr(key, "name", None)
            if name == "esc" and {"ctrl", "alt"}.issubset(self._stop_chord_keys):
                self.stop()
                return False
            if name in ("ctrl", "ctrl_l", "ctrl_r"):
                self._stop_chord_keys.discard("ctrl")
            elif name in ("alt", "alt_l", "alt_r"):
                self._stop_chord_keys.discard("alt")
            return None

        def on_move(x: int, y: int) -> None:
            with self._position_lock:
                previous = self._position
                self._position = (x, y)
            if previous is not None:
                dx, dy = x - previous[0], y - previous[1]
                if dx or dy:
                    send({"type": "move", "dx": dx, "dy": dy})

        def on_click(x: int, y: int, button: Any, pressed: bool) -> None:
            name = getattr(button, "name", None)
            if name in ("left", "right", "middle"):
                send({"type": "button_down" if pressed else "button_up", "button": name})

        def on_scroll(x: int, y: int, dx: int, dy: int) -> None:
            send({"type": "scroll", "dx": max(-MAX_SCROLL_DELTA, min(MAX_SCROLL_DELTA, dx)),
                  "dy": max(-MAX_SCROLL_DELTA, min(MAX_SCROLL_DELTA, dy))})

        self._keyboard_listener = keyboard.Listener(
            on_press=on_press, on_release=on_release, suppress=True
        )
        self._mouse_listener = mouse.Listener(
            on_move=on_move, on_click=on_click, on_scroll=on_scroll, suppress=True
        )
        self._keyboard_listener.start()
        self._mouse_listener.start()

    def stop(self) -> None:
        self._stopped.set()
        for listener in (self._keyboard_listener, self._mouse_listener):
            if listener:
                listener.stop()
        self._keyboard_listener = None
        self._mouse_listener = None
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
            self._socket = None
        self._set_status("Stopped")
