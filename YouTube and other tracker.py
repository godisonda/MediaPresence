import os
import sys
import json
import time
import secrets
import threading
import asyncio
import ctypes
import winreg
from io import BytesIO

import websockets
from PIL import Image
import requests
import customtkinter as ctk
from pypresence import Presence
import keyboard

MY_APP_ID = "mediahub.presence.tracker.final"
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MY_APP_ID)
except Exception:
    pass

CLIENT_ID = "1556376533864554566" 

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def restart_as_admin():
    executable = sys.executable if getattr(sys, 'frozen', False) else sys.executable
    params = f'"{os.path.abspath(sys.argv[0])}"' if not getattr(sys, 'frozen', False) else ""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
    sys.exit(0)

APP_DIR = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

def load_config():
    default_cfg = {
        "token": secrets.token_hex(3).upper(),
        "theme": "Dark",
        "hotkey_toggle": "alt+k",
        "hotkey_next": "alt+l",
        "hotkey_prev": "alt+j"
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                default_cfg.update(d)
        except Exception:
            pass
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, indent=2)
    except Exception:
        pass
    return default_cfg

APP_CONFIG = load_config()
AUTH_TOKEN = APP_CONFIG["token"]

# --- Discord RPC ---
rpc = None
rpc_lock = threading.Lock()

def recreate_rpc_connection():
    global rpc
    with rpc_lock:
        if rpc:
            try:
                rpc.close()
            except Exception:
                pass
            rpc = None
        time.sleep(0.3)
        try:
            rpc = Presence(CLIENT_ID)
            rpc.connect()
        except Exception:
            rpc = None

threading.Thread(target=recreate_rpc_connection, daemon=True).start()

current_media = {
    "title": "Ничего не играет",
    "channel": "Включите трек или видео",
    "platform": "Медиаплеер",
    "coverUrl": "",
    "currentTime": 0,
    "duration": 0,
    "isPaused": True
}
app_instance = None

last_sent_track = ""
last_sent_paused = None

def fmt_time(seconds):
    seconds = int(seconds)
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"

def update_discord_presence():
    global rpc
    with rpc_lock:
        if not rpc:
            return
        try:
            cur = int(current_media.get("currentTime", 0))
            dur = int(current_media.get("duration", 0))

            status_text = f"⏸ {current_media['title']}" if current_media["isPaused"] else current_media['title']
            platform_name = current_media.get('platform') or 'Медиаплеер'

            update_args = {
                "details": status_text[:128],
                "state": f"{current_media['channel']} [{platform_name}]"[:128],
                "large_image": current_media.get("coverUrl") or "yt_icon",
                "large_text": platform_name,
                "buttons": [{"label": "Слушать онлайн", "url": current_media.get("url", "https://music.yandex.ru")}]
            }

            if not current_media["isPaused"] and dur > 0:
                now = int(time.time())
                update_args["start"] = now - cur
                update_args["end"] = (now - cur) + dur

            rpc.update(**update_args)
        except Exception:
            pass

def handle_track_change_worker():
    recreate_rpc_connection()
    update_discord_presence()


connected_clients = set()
ws_loop = None

async def ws_handler(websocket):
    global last_sent_track, last_sent_paused
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                msg = json.loads(message)
                if msg.get("token") != AUTH_TOKEN:
                    continue

                if msg.get("type") == "media_update":
                    data = msg.get("data", {})
                    new_title = data.get("title", "").strip()
                    new_paused = data.get("isPaused", True)

                    for k in current_media:
                        if k in data:
                            current_media[k] = data[k]

                    if app_instance:
                        app_instance.after(0, app_instance.update_media_ui)

                    if not new_title or new_title == "Ничего не играет":
                        continue

                    if new_title != last_sent_track:
                        last_sent_track = new_title
                        last_sent_paused = new_paused
                        threading.Thread(target=handle_track_change_worker, daemon=True).start()
                    elif new_paused != last_sent_paused:
                        last_sent_paused = new_paused
                        threading.Thread(target=update_discord_presence, daemon=True).start()

            except Exception:
                pass
    finally:
        connected_clients.discard(websocket)

async def _send_command_async(cmd):
    if not connected_clients:
        return
    payload = json.dumps({"command": cmd})
    dead_clients = set()
    for ws in list(connected_clients):
        try:
            await ws.send(payload)
        except Exception:
            dead_clients.add(ws)
    connected_clients.difference_update(dead_clients)

def broadcast_command(cmd):
    if ws_loop and ws_loop.is_running():
        asyncio.run_coroutine_threadsafe(_send_command_async(cmd), ws_loop)

def start_websocket_server():
    global ws_loop
    ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ws_loop)

    async def main():
        async with websockets.serve(ws_handler, "127.0.0.1", 6412):
            await asyncio.Future()

    ws_loop.run_until_complete(main())

threading.Thread(target=start_websocket_server, daemon=True).start()

ctk.set_appearance_mode(APP_CONFIG.get("theme", "Dark"))

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Настройки")
        self.geometry("380x430")
        self.resizable(False, False)
        self.grab_set()

        ctk.CTkLabel(self, text="Тема оформления", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=20, pady=(16, 4))
        self.theme_menu = ctk.CTkOptionMenu(
            self, 
            values=["Dark", "Light", "System"], 
            command=self.change_theme,
            fg_color="#272930",
            button_color="#32353E"
        )
        self.theme_menu.set(APP_CONFIG.get("theme", "Dark"))
        self.theme_menu.pack(fill="x", padx=20)

        ctk.CTkLabel(self, text="Система", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=20, pady=(16, 4))
        self.autostart_var = ctk.BooleanVar(value=parent.check_autostart())
        self.autostart_cb = ctk.CTkCheckBox(
            self, 
            text="Запускать при старте Windows", 
            variable=self.autostart_var, 
            command=parent.toggle_autostart,
            font=("Segoe UI", 11)
        )
        self.autostart_cb.pack(anchor="w", padx=20, pady=4)

        admin_status = "Да" if is_admin() else "Нет"
        self.admin_lbl = ctk.CTkLabel(
            self, 
            text=f"Запуск от Администратора: {admin_status}", 
            font=("Segoe UI", 11), 
            text_color="#10B981" if is_admin() else "#F59E0B"
        )
        self.admin_lbl.pack(anchor="w", padx=20, pady=(4, 6))

        if not is_admin():
            self.elevate_btn = ctk.CTkButton(
                self, 
                text="Перезапустить от Администратора", 
                fg_color="#D97706", 
                hover_color="#B45309",
                height=26,
                command=restart_as_admin
            )
            self.elevate_btn.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkLabel(self, text="Глобальные хоткеи", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=20, pady=(12, 4))

        self.hk_toggle_entry = self._create_hk_row("Пауза / Плей:", APP_CONFIG.get("hotkey_toggle", "alt+k"))
        self.hk_prev_entry = self._create_hk_row("Предыдущий трек:", APP_CONFIG.get("hotkey_prev", "alt+j"))
        self.hk_next_entry = self._create_hk_row("Следующий трек:", APP_CONFIG.get("hotkey_next", "alt+l"))

        self.save_btn = ctk.CTkButton(
            self, 
            text="Сохранить настройки", 
            fg_color="#4F46E5", 
            hover_color="#4338CA",
            command=self.save_and_close
        )
        self.save_btn.pack(side="bottom", fill="x", padx=20, pady=16)

    def _create_hk_row(self, label, val):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=2)
        ctk.CTkLabel(row, text=label, font=("Segoe UI", 11), width=120, anchor="w").pack(side="left")
        e = ctk.CTkEntry(row, width=120, font=("Consolas", 11))
        e.insert(0, val)
        e.pack(side="right")
        return e

    def change_theme(self, choice):
        ctk.set_appearance_mode(choice)
        APP_CONFIG["theme"] = choice

    def save_and_close(self):
        APP_CONFIG["hotkey_toggle"] = self.hk_toggle_entry.get().strip().lower()
        APP_CONFIG["hotkey_prev"] = self.hk_prev_entry.get().strip().lower()
        APP_CONFIG["hotkey_next"] = self.hk_next_entry.get().strip().lower()
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(APP_CONFIG, f, indent=2)
        except Exception:
            pass
        self.parent.register_global_hotkeys()
        self.destroy()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Media Presence")
        self.geometry("490x305")
        self.resizable(False, False)

        self.top_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.top_bar.pack(fill="x", padx=20, pady=(16, 8))

        self.brand_badge = ctk.CTkLabel(
            self.top_bar, 
            text="● WS LIVE", 
            font=("Segoe UI", 10, "bold"), 
            text_color="#10B981"
        )
        self.brand_badge.pack(side="left")

        self.right_top_frame = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        self.right_top_frame.pack(side="right")

        self.settings_btn = ctk.CTkButton(
            self.right_top_frame,
            text="⚙ Настройки",
            width=85,
            height=24,
            font=("Segoe UI", 11),
            fg_color="#272930",
            hover_color="#32353E",
            corner_radius=6,
            command=self.open_settings
        )
        self.settings_btn.pack(side="right", padx=(8, 0))

        self.token_container = ctk.CTkFrame(self.right_top_frame, fg_color="#18191D", corner_radius=6)
        self.token_container.pack(side="right")

        self.token_lbl = ctk.CTkLabel(
            self.token_container, 
            text=f"PIN: {AUTH_TOKEN}", 
            font=("Consolas", 12, "bold"), 
            text_color="#D1D5DB"
        )
        self.token_lbl.pack(side="left", padx=(8, 4), pady=2)

        self.copy_btn = ctk.CTkButton(
            self.token_container, 
            text="Копировать", 
            width=70, 
            height=20, 
            font=("Segoe UI", 10),
            fg_color="#272930", 
            hover_color="#32353E",
            corner_radius=4,
            command=self.copy_code
        )
        self.copy_btn.pack(side="left", padx=3, pady=2)

        self.card = ctk.CTkFrame(self, fg_color="#18191D", corner_radius=12, border_width=1, border_color="#26282E")
        self.card.pack(fill="x", padx=20, pady=(0, 10))

        self.cover_frame = ctk.CTkFrame(self.card, width=88, height=88, corner_radius=8, fg_color="#22242A")
        self.cover_frame.pack_propagate(False)
        self.cover_frame.grid(row=0, column=0, rowspan=4, padx=14, pady=14)

        self.cover_label = ctk.CTkLabel(self.cover_frame, text="", fg_color="transparent")
        self.cover_label.place(relx=0.5, rely=0.5, anchor="center")

        self.title_lbl = ctk.CTkLabel(
            self.card, 
            text=current_media["title"], 
            font=("Segoe UI", 13, "bold"), 
            text_color="#F4F4F5",
            anchor="w", 
            wraplength=310
        )
        self.title_lbl.grid(row=0, column=1, sticky="w", padx=(0, 14), pady=(12, 2))

        self.channel_lbl = ctk.CTkLabel(
            self.card, 
            text=current_media["channel"], 
            font=("Segoe UI", 11), 
            text_color="#9CA3AF", 
            anchor="w", 
            wraplength=310
        )
        self.channel_lbl.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=(0, 6))

        self.progress_container = ctk.CTkFrame(self.card, fg_color="transparent")
        self.progress_container.grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=(0, 6))

        self.prog_bar = ctk.CTkProgressBar(
            self.progress_container, 
            width=230, 
            height=4, 
            progress_color="#6366F1", 
            fg_color="#2B2D35"
        )
        self.prog_bar.set(0)
        self.prog_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.time_lbl = ctk.CTkLabel(
            self.progress_container, 
            text="00:00 / 00:00", 
            font=("Consolas", 10), 
            text_color="#6B7280"
        )
        self.time_lbl.pack(side="right")

        self.controls_frame = ctk.CTkFrame(self.card, fg_color="transparent")
        self.controls_frame.grid(row=3, column=1, sticky="w", padx=(0, 14), pady=(0, 12))

        self.prev_btn = ctk.CTkButton(
            self.controls_frame, 
            text="⏮ Пред", 
            width=65, 
            height=26, 
            font=("Segoe UI", 11),
            fg_color="#272930", 
            hover_color="#32353E",
            corner_radius=6,
            command=lambda: broadcast_command("prev")
        )
        self.prev_btn.pack(side="left", padx=(0, 6))

        self.play_btn = ctk.CTkButton(
            self.controls_frame, 
            text="⏯ Пауза", 
            width=80, 
            height=26, 
            font=("Segoe UI", 11, "bold"),
            fg_color="#4F46E5", 
            hover_color="#4338CA",
            corner_radius=6,
            command=lambda: broadcast_command("toggle")
        )
        self.play_btn.pack(side="left", padx=(0, 6))

        self.next_btn = ctk.CTkButton(
            self.controls_frame, 
            text="След ⏭", 
            width=65, 
            height=26, 
            font=("Segoe UI", 11),
            fg_color="#272930", 
            hover_color="#32353E",
            corner_radius=6,
            command=lambda: broadcast_command("next")
        )
        self.next_btn.pack(side="left")

        self.last_cover_url = ""
        self.settings_win = None

        self.register_global_hotkeys()

    def open_settings(self):
        if self.settings_win is None or not self.settings_win.winfo_exists():
            self.settings_win = SettingsWindow(self)
        else:
            self.settings_win.focus()

    def register_global_hotkeys(self):
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        def bind_safe(hk, cmd):
            if hk:
                try:
                    keyboard.add_hotkey(hk, lambda: broadcast_command(cmd), suppress=False)
                except Exception:
                    pass

        bind_safe(APP_CONFIG.get("hotkey_toggle"), "toggle")
        bind_safe(APP_CONFIG.get("hotkey_next"), "next")
        bind_safe(APP_CONFIG.get("hotkey_prev"), "prev")

    def copy_code(self):
        self.clipboard_clear()
        self.clipboard_append(AUTH_TOKEN)
        self.copy_btn.configure(text="OK")
        self.after(1400, lambda: self.copy_btn.configure(text="Копировать"))

    def update_media_ui(self):
        self.title_lbl.configure(text=current_media["title"])
        badge = f"[{current_media['platform']}] " if current_media['platform'] else ""
        self.channel_lbl.configure(text=f"{badge}{current_media['channel']}")

        cur = current_media["currentTime"]
        dur = current_media["duration"]
        if dur > 0:
            self.prog_bar.set(min(max(cur / dur, 0.0), 1.0))
            self.time_lbl.configure(text=f"{fmt_time(cur)} / {fmt_time(dur)}")
        else:
            self.prog_bar.set(0)
            self.time_lbl.configure(text="00:00 / 00:00")

        self.play_btn.configure(text="Плей" if current_media["isPaused"] else "Пауза")

        if current_media["coverUrl"] and current_media["coverUrl"] != self.last_cover_url:
            self.last_cover_url = current_media["coverUrl"]
            threading.Thread(target=self.fetch_cover, args=(self.last_cover_url,), daemon=True).start()

    def fetch_cover(self, url):
        try:
            r = requests.get(url, timeout=2.5)
            img = Image.open(BytesIO(r.content))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(88, 88))
            self.cover_label.configure(image=ctk_img, text="")
        except Exception:
            pass

    def check_autostart(self):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            winreg.QueryValueEx(k, "MediaPresenceApp")
            winreg.CloseKey(k)
            return True
        except Exception:
            pass

    def toggle_autostart(self):
        p = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            if self.check_autostart():
                try:
                    winreg.DeleteValue(k, "MediaPresenceApp")
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(k, "MediaPresenceApp", 0, winreg.REG_SZ, f'"{p}"')
            winreg.CloseKey(k)
        except Exception:
            pass

if __name__ == "__main__":
    app_instance = App()
    app_instance.mainloop()