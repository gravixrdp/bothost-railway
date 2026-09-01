import asyncio
import os
import sys
import time
import logging
import html
import tempfile
import zipfile
import psutil
from datetime import datetime
from collections import deque
from typing import Dict, Optional, Tuple, Any
import database
from config import DATA_DIR, MAX_LOG_LINES

logger = logging.getLogger("GravixHost.BotManager")

class BotProcessManager:
    def __init__(self):
        self.active_processes: Dict[str, asyncio.subprocess.Process] = {}
        self.log_buffers: Dict[str, deque] = {}
        self.log_tasks: Dict[str, asyncio.Task] = {}
        self.restart_history: Dict[str, deque] = {}
        self._telegram_bot: Optional[Any] = None

    def set_telegram_bot_instance(self, bot: Any):
        """Sets the Telegram bot instance used for sending notification DMs."""
        self._telegram_bot = bot

    def get_log_file_path(self, bot_id: str) -> str:
        bot_id = str(bot_id).strip()
        log_dir = os.path.join(DATA_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"{bot_id}.log")

    def _append_system_log(self, bot_id: str, message: str):
        bot_id = str(bot_id).strip()
        log_file = self.get_log_file_path(bot_id)
        if bot_id not in self.log_buffers:
            self.log_buffers[bot_id] = deque(maxlen=MAX_LOG_LINES)
        
        ts = datetime.utcnow().strftime("%H:%M:%S")
        formatted = f"[{ts}] {message}"
        self.log_buffers[bot_id].append(formatted)
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception as e:
            logger.error(f"Failed writing system log for bot {bot_id}: {e}")

    async def _stream_logs(self, bot_id: str, stream, prefix: str = ""):
        bot_id = str(bot_id).strip()
        log_file = self.get_log_file_path(bot_id)
        if bot_id not in self.log_buffers:
            self.log_buffers[bot_id] = deque(maxlen=MAX_LOG_LINES)

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded_line = line.decode("utf-8", errors="replace").rstrip()
                    if not decoded_line:
                        continue
                    ts = datetime.utcnow().strftime("%H:%M:%S")
                    formatted = f"[{ts}] {prefix}{decoded_line}" if prefix else f"[{ts}] {decoded_line}"
                    self.log_buffers[bot_id].append(formatted)
                    f.write(formatted + "\n")
                    f.flush()
        except Exception as e:
            logger.error(f"Error streaming logs for bot {bot_id}: {e}")

    def _get_startup_error_snippet(self, bot_id: str, max_lines: int = 10) -> str:
        bot_id = str(bot_id).strip()

        def sanitize_log(txt: str) -> str:
            if not txt:
                return txt
            txt = re.sub(r"/var/lib/containers/[a-zA-Z0-9_\-\./]+", "/cloud/data", txt)
            txt = re.sub(r"railwayapp", "gravixcloud", txt, flags=re.IGNORECASE)
            txt = re.sub(r"railway", "gravix", txt, flags=re.IGNORECASE)
            return txt

        # Check in-memory buffer first
        if bot_id in self.log_buffers and self.log_buffers[bot_id]:
            lines = list(self.log_buffers[bot_id])
            content_lines = [l for l in lines if not ("[SYSTEM] Process started" in l)]
            target = content_lines if content_lines else lines
            if target:
                return "\n".join([sanitize_log(l) for l in target[-max_lines:]])

        # Fallback to reading file
        log_file = self.get_log_file_path(bot_id)
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    file_lines = [sanitize_log(line.rstrip()) for line in f.readlines() if line.strip()]
                    if file_lines:
                        return "\n".join(file_lines[-max_lines:])
            except Exception as e:
                logger.error(f"Error reading log file for snippet: {e}")

        return "No stderr output captured."

    async def start_bot(self, bot_id: str) -> Tuple[bool, str]:
        bot_id = str(bot_id).strip()
        if bot_id in self.active_processes and self.active_processes[bot_id].returncode is None:
            return False, "Bot is already running and active."

        bot_data = database.get_bot(bot_id)
        if not bot_data:
            return False, "Bot record not found in database."

        script_path = bot_data.get('script_path')
        if not script_path or not os.path.exists(script_path):
            return False, f"Script file not found at {script_path}"

        working_dir = os.path.dirname(script_path)
        env = os.environ.copy()

        # Load custom environment variables from database
        try:
            if hasattr(database, "get_bot_env_vars"):
                custom_env = database.get_bot_env_vars(bot_id) or {}
                if isinstance(custom_env, dict):
                    for k, v in custom_env.items():
                        env[str(k)] = str(v)
        except Exception as e:
            logger.error(f"Error loading custom env vars for bot {bot_id}: {e}")

        # Standard system-injected environment variables
        env["BOT_TOKEN"] = bot_data['bot_token']
        env["OWNER_ID"] = str(bot_data['user_id'])
        env["PYTHONUNBUFFERED"] = "1"

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env
            )
            self.active_processes[bot_id] = process

            # Start background log streaming tasks
            t1 = asyncio.create_task(self._stream_logs(bot_id, process.stdout))
            t2 = asyncio.create_task(self._stream_logs(bot_id, process.stderr, prefix="[STDERR] "))
            self.log_tasks[bot_id] = asyncio.gather(t1, t2)

            # 1.5-second startup liveness probe
            await asyncio.sleep(1.5)

            if process.returncode is not None:
                # Process died on boot
                self.active_processes.pop(bot_id, None)
                await asyncio.sleep(0.1)  # Allow log streaming tasks to drain
                stderr_snippet = self._get_startup_error_snippet(bot_id)
                database.update_bot_status(bot_id, "FAILED")
                self._append_system_log(bot_id, f"❌ [SYSTEM] Process crashed on startup (Exit code {process.returncode})")
                logger.warning(f"Bot {bot_id} crashed on startup with exit code {process.returncode}")
                return False, f"Process crashed on startup (Exit code {process.returncode}):\n{stderr_snippet}"

            # Process is actively running after 1.5s
            database.update_bot_status(bot_id, "RUNNING")
            self._append_system_log(bot_id, f"🚀 [SYSTEM] Process started successfully (PID: {process.pid})")
            logger.info(f"Bot {bot_id} ({bot_data.get('bot_name', 'Unnamed')}) started with PID {process.pid}")
            return True, f"Bot started successfully (PID: {process.pid})"
        except Exception as e:
            logger.exception(f"Failed to start bot {bot_id}: {e}")
            self.active_processes.pop(bot_id, None)
            database.update_bot_status(bot_id, "FAILED")
            self._append_system_log(bot_id, f"❌ [SYSTEM] Failed to start process: {str(e)}")
            return False, f"Failed to start bot: {str(e)}"

    async def stop_bot(self, bot_id: str) -> Tuple[bool, str]:
        bot_id = str(bot_id).strip()
        process = self.active_processes.get(bot_id)
        if not process or process.returncode is not None:
            self.active_processes.pop(bot_id, None)
            self.restart_history.pop(bot_id, None)
            database.update_bot_status(bot_id, "STOPPED")
            return True, "Bot is not currently running."

        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

            self.active_processes.pop(bot_id, None)
            self.restart_history.pop(bot_id, None)
            database.update_bot_status(bot_id, "STOPPED")
            self._append_system_log(bot_id, "⏹️ [SYSTEM] Process stopped successfully.")
            logger.info(f"Bot {bot_id} stopped.")
            return True, "Bot stopped successfully."
        except Exception as e:
            logger.error(f"Error stopping bot {bot_id}: {e}")
            return False, f"Failed to stop bot: {str(e)}"

    async def restart_bot(self, bot_id: str) -> Tuple[bool, str]:
        bot_id = str(bot_id).strip()
        await self.stop_bot(bot_id)
        await asyncio.sleep(1)
        success, msg = await self.start_bot(bot_id)
        if success:
            return True, msg.replace("started", "restarted")
        return False, f"Failed to restart bot: {msg}"

    def get_logs(self, bot_id: str, lines: int = 25) -> str:
        bot_id = str(bot_id).strip()
        lines = max(1, int(lines))

        def sanitize_log(txt: str) -> str:
            if not txt:
                return txt
            txt = re.sub(r"/var/lib/containers/[a-zA-Z0-9_\-\./]+", "/cloud/data", txt)
            txt = re.sub(r"railwayapp", "gravixcloud", txt, flags=re.IGNORECASE)
            txt = re.sub(r"railway", "gravix", txt, flags=re.IGNORECASE)
            return txt

        # Check in-memory buffer first
        if bot_id in self.log_buffers and self.log_buffers[bot_id]:
            recent = [sanitize_log(l) for l in list(self.log_buffers[bot_id])[-lines:]]
            if recent:
                header = f"Live Logs for #{bot_id} (Last {len(recent)} lines)\n━━━━━━━━━━━━━━━━━━━━━━"
                return f"{header}\n" + "\n".join(recent)

        # Fallback to reading file
        log_file = self.get_log_file_path(bot_id)
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    file_lines = [sanitize_log(line.rstrip()) for line in f.readlines() if line.strip()]
                    if file_lines:
                        recent = file_lines[-lines:]
                        header = f"Logs for #{bot_id} (Last {len(recent)} lines)\n━━━━━━━━━━━━━━━━━━━━━━"
                        return f"{header}\n" + "\n".join(recent)
            except Exception as e:
                return f"Error reading log file: {e}"

        return "No console logs recorded yet for this bot."

    def is_running(self, bot_id: str) -> bool:
        bot_id = str(bot_id).strip()
        process = self.active_processes.get(bot_id)
        return process is not None and process.returncode is None

    def get_bot_process_metrics(self, bot_id: str) -> dict:
        """Retrieves real-time CPU & RAM telemetry metrics for a running bot process."""
        bot_id = str(bot_id).strip()
        process = self.active_processes.get(bot_id)
        if process and process.returncode is None and process.pid:
            try:
                p = psutil.Process(process.pid)
                cpu_percent = p.cpu_percent(interval=None)
                ram_mb = p.memory_info().rss / (1024 * 1024)
                return {
                    'is_running': True,
                    'pid': process.pid,
                    'cpu_percent': round(cpu_percent, 1),
                    'ram_mb': round(ram_mb, 1)
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
            except Exception as e:
                logger.error(f"Error getting process metrics for bot {bot_id}: {e}")
        return {'is_running': False, 'pid': None, 'cpu_percent': 0.0, 'ram_mb': 0.0}

    def create_bot_backup_zip(self, bot_id: str, user_id: int) -> Optional[str]:
        """Creates a .zip archive of the hosted bot's data directory and returns its absolute path."""
        bot_id = str(bot_id).strip()
        try:
            uid = int(user_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid user_id provided for backup: {user_id}")
            return None

        bot_dir = os.path.join(DATA_DIR, "bots", f"{uid}_{bot_id}")
        if not os.path.exists(bot_dir) or not os.path.isdir(bot_dir):
            bot_data = database.get_bot(bot_id)
            if bot_data and bot_data.get('script_path'):
                alt_dir = os.path.dirname(bot_data['script_path'])
                if os.path.exists(alt_dir) and os.path.isdir(alt_dir):
                    bot_dir = alt_dir
                else:
                    return None
            else:
                return None

        try:
            temp_dir = tempfile.gettempdir()
            zip_filename = f"backup_{uid}_{bot_id}_{int(time.time())}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(bot_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, start=bot_dir)
                        zipf.write(file_path, arcname=arcname)

            return os.path.abspath(zip_path)
        except Exception as e:
            logger.error(f"Failed to create backup zip for bot {bot_id}: {e}")
            return None

    async def _send_crash_alert(
        self,
        bot_id: str,
        bot_data: Optional[Dict[str, Any]] = None,
        restarts: Optional[int] = None,
        action: Optional[str] = None,
        status_text: Optional[str] = None,
        bot: Any = None
    ):
        """Sends an alert DM to the bot owner when an unexpected crash or crash-loop occurs."""
        tg_bot = bot or self._telegram_bot
        if not tg_bot:
            return

        bot_rec = bot_data or database.get_bot(bot_id)
        if not bot_rec:
            return

        owner_id = bot_rec.get('user_id')
        if not owner_id:
            return

        bot_name = bot_rec.get('bot_name') or f"Bot #{bot_id}"
        status_display = status_text or "Unexpected Process Termination"
        if action:
            action_display = action
        elif restarts is not None:
            action_display = f"Watchdog restart triggered (Attempt {restarts}/5)"
        else:
            action_display = "Unexpected process exit."

        alert_text = (
            "<b>⚠️ GRAVIX-HOST INSTANCE CRASH ALERT</b>\n"
            "<i>Automatic Diagnostics Notification</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>\n"
            f"🤖 <b>Bot Instance:</b> {html.escape(str(bot_name))} (<code>{html.escape(str(bot_id))}</code>)\n"
            f"⚡ <b>Status:</b> {html.escape(str(status_display))}\n"
            f"🔄 <b>Action:</b> {html.escape(str(action_display))}\n"
            "💡 <b>Recommendation:</b> Check your script logs in <b>🤖 My Hosted Bots</b> for tracebacks.\n"
            "</blockquote>"
        )

        try:
            await tg_bot.send_message(chat_id=owner_id, text=alert_text, parse_mode="HTML")
            logger.info(f"Sent crash alert DM to owner {owner_id} for bot {bot_id}.")
        except Exception as e:
            logger.warning(f"Failed to send crash alert DM to user {owner_id} for bot {bot_id}: {e}")

    async def watchdog_loop(self, bot: Any = None):
        """Monitors running child processes and marks crashed ones."""
        if bot is not None:
            self._telegram_bot = bot

        while True:
            try:
                tg_bot = bot or self._telegram_bot
                for bot_id, process in list(self.active_processes.items()):
                    if process.returncode is not None:
                        # Process exited unexpectedly
                        self.active_processes.pop(bot_id, None)
                        bot_data = database.get_bot(bot_id)
                        if bot_data and bot_data.get('auto_restart') and bot_data['status'] in ('RUNNING', 'RESTARTING'):
                            # Crash-loop guard: if a bot keeps dying, stop auto-restarting it.
                            now = time.monotonic()
                            hist = self.restart_history.setdefault(bot_id, deque(maxlen=20))
                            while hist and (now - hist[0]) > 120:
                                hist.popleft()
                            if len(hist) >= 5:
                                hist.clear()
                                database.update_bot_status(bot_id, "CRASHED")
                                self._append_system_log(bot_id, "⛔ [SYSTEM] Crash loop detected (5+ restarts in <120s). Auto-restart disabled.")
                                logger.error(f"Bot {bot_id} is crash-looping (5+ restarts in <120s). Auto-restart disabled; marked CRASHED.")
                                if tg_bot:
                                    await self._send_crash_alert(
                                        bot_id=bot_id,
                                        bot_data=bot_data,
                                        status_text="Unexpected Process Termination",
                                        action="Crash-loop limit reached (5 restarts in <120s). Auto-restart disabled.",
                                        bot=tg_bot
                                    )
                                continue
                            hist.append(now)
                            restarts = len(hist)
                            self._append_system_log(bot_id, f"🔄 [SYSTEM] Process exited (code {process.returncode}). Auto-restarting ({restarts}/5)...")
                            logger.warning(f"Bot {bot_id} exited with code {process.returncode}. Auto-restarting ({restarts}/5)...")
                            database.update_bot_status(bot_id, "RESTARTING")
                            if tg_bot:
                                await self._send_crash_alert(
                                    bot_id=bot_id,
                                    bot_data=bot_data,
                                    restarts=restarts,
                                    bot=tg_bot
                                )
                            await asyncio.sleep(2)
                            await self.start_bot(bot_id)
                        else:
                            self.restart_history.pop(bot_id, None)
                            status = "CRASHED" if process.returncode != 0 else "STOPPED"
                            database.update_bot_status(bot_id, status)
                            self._append_system_log(bot_id, f"ℹ️ [SYSTEM] Process exited with status code {process.returncode} (marked {status}).")
                            logger.info(f"Bot {bot_id} exited with status {process.returncode}.")
                            if tg_bot and process.returncode != 0:
                                await self._send_crash_alert(
                                    bot_id=bot_id,
                                    bot_data=bot_data,
                                    status_text="Unexpected Process Termination",
                                    action="Auto-restart is disabled. Process marked as CRASHED.",
                                    bot=tg_bot
                                )
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            await asyncio.sleep(5)

    def start_watchdog(self, bot: Any = None):
        """Starts the background watchdog loop task."""
        if bot is not None:
            self._telegram_bot = bot
        if not hasattr(self, '_watchdog_task') or self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self.watchdog_loop(bot=bot))
        return self._watchdog_task

bot_manager = BotProcessManager()

def set_telegram_bot_instance(bot: Any):
    """Module-level helper to register the Telegram bot instance for DM alerts."""
    bot_manager.set_telegram_bot_instance(bot)

def start_watchdog(bot: Any = None):
    """Module-level helper to start the background watchdog loop."""
    return bot_manager.start_watchdog(bot)

def get_bot_process_metrics(bot_id: str) -> dict:
    """Module-level helper to get real-time CPU & RAM metrics for a hosted bot."""
    return bot_manager.get_bot_process_metrics(bot_id)

def create_bot_backup_zip(bot_id: str, user_id: int) -> Optional[str]:
    """Module-level helper to create a backup .zip archive for a hosted bot."""
    return bot_manager.create_bot_backup_zip(bot_id, user_id)


