import asyncio
import os
import sys
import time
import logging
from datetime import datetime
from collections import deque
from typing import Dict, Optional, Tuple
import database
from config import DATA_DIR, MAX_LOG_LINES

logger = logging.getLogger("GravixHost.BotManager")

class BotProcessManager:
    def __init__(self):
        self.active_processes: Dict[str, asyncio.subprocess.Process] = {}
        self.log_buffers: Dict[str, deque] = {}
        self.log_tasks: Dict[str, asyncio.Task] = {}
        self.restart_history: Dict[str, deque] = {}

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
            database.update_bot_status(bot_id, "RUNNING")

            # Append system log entry
            self._append_system_log(bot_id, f"🚀 [SYSTEM] Process started successfully (PID: {process.pid})")

            # Start background log streaming tasks
            t1 = asyncio.create_task(self._stream_logs(bot_id, process.stdout))
            t2 = asyncio.create_task(self._stream_logs(bot_id, process.stderr, prefix="[STDERR] "))
            self.log_tasks[bot_id] = asyncio.gather(t1, t2)

            logger.info(f"Bot {bot_id} ({bot_data.get('bot_name', 'Unnamed')}) started with PID {process.pid}")
            return True, f"Bot started successfully (PID: {process.pid})"
        except Exception as e:
            logger.exception(f"Failed to start bot {bot_id}: {e}")
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

        # Check in-memory buffer first
        if bot_id in self.log_buffers and self.log_buffers[bot_id]:
            recent = list(self.log_buffers[bot_id])[-lines:]
            if recent:
                header = f"=== Live Logs for #{bot_id} (Last {len(recent)} lines) ==="
                return f"{header}\n" + "\n".join(recent)

        # Fallback to reading file
        log_file = self.get_log_file_path(bot_id)
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    file_lines = [line.rstrip() for line in f.readlines() if line.strip()]
                    if file_lines:
                        recent = file_lines[-lines:]
                        header = f"=== Logs for #{bot_id} (Last {len(recent)} lines) ==="
                        return f"{header}\n" + "\n".join(recent)
            except Exception as e:
                return f"Error reading log file: {e}"

        return "No console logs recorded yet for this bot."

    def is_running(self, bot_id: str) -> bool:
        bot_id = str(bot_id).strip()
        process = self.active_processes.get(bot_id)
        return process is not None and process.returncode is None

    async def watchdog_loop(self):
        """Monitors running child processes and marks crashed ones."""
        while True:
            try:
                for bot_id, process in list(self.active_processes.items()):
                    if process.returncode is not None:
                        # Process exited
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
                                continue
                            hist.append(now)
                            self._append_system_log(bot_id, f"🔄 [SYSTEM] Process exited (code {process.returncode}). Auto-restarting ({len(hist)}/5)...")
                            logger.warning(f"Bot {bot_id} exited with code {process.returncode}. Auto-restarting ({len(hist)}/5)...")
                            database.update_bot_status(bot_id, "RESTARTING")
                            await asyncio.sleep(2)
                            await self.start_bot(bot_id)
                        else:
                            self.restart_history.pop(bot_id, None)
                            status = "CRASHED" if process.returncode != 0 else "STOPPED"
                            database.update_bot_status(bot_id, status)
                            self._append_system_log(bot_id, f"ℹ️ [SYSTEM] Process exited with status code {process.returncode} (marked {status}).")
                            logger.info(f"Bot {bot_id} exited with status {process.returncode}.")
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            await asyncio.sleep(5)

bot_manager = BotProcessManager()

