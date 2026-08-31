import asyncio
import os
import sys
import time
import logging
from collections import deque
from typing import Dict, Optional
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
        return os.path.join(DATA_DIR, "logs", f"{bot_id}.log")

    async def _stream_logs(self, bot_id: str, stream, prefix: str = ""):
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
                    formatted = f"{prefix}{decoded_line}" if prefix else decoded_line
                    self.log_buffers[bot_id].append(formatted)
                    f.write(formatted + "\n")
                    f.flush()
        except Exception as e:
            logger.error(f"Error streaming logs for bot {bot_id}: {e}")

    async def start_bot(self, bot_id: str) -> tuple[bool, str]:
        if bot_id in self.active_processes and self.active_processes[bot_id].returncode is None:
            return False, "Bot is already running."

        bot_data = database.get_bot(bot_id)
        if not bot_data:
            return False, "Bot record not found in database."

        script_path = bot_data['script_path']
        if not os.path.exists(script_path):
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

            # Start background log streaming tasks
            t1 = asyncio.create_task(self._stream_logs(bot_id, process.stdout))
            t2 = asyncio.create_task(self._stream_logs(bot_id, process.stderr, prefix="[STDERR] "))
            self.log_tasks[bot_id] = asyncio.gather(t1, t2)

            logger.info(f"Bot {bot_id} ({bot_data['bot_name']}) started with PID {process.pid}")
            return True, f"Bot started successfully (PID: {process.pid})"
        except Exception as e:
            logger.exception(f"Failed to start bot {bot_id}: {e}")
            database.update_bot_status(bot_id, "FAILED")
            return False, f"Execution failed: {str(e)}"

    async def stop_bot(self, bot_id: str) -> tuple[bool, str]:
        process = self.active_processes.get(bot_id)
        if not process or process.returncode is not None:
            database.update_bot_status(bot_id, "STOPPED")
            return True, "Bot was not running."

        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

            self.active_processes.pop(bot_id, None)
            database.update_bot_status(bot_id, "STOPPED")
            logger.info(f"Bot {bot_id} stopped.")
            return True, "Bot stopped successfully."
        except Exception as e:
            logger.error(f"Error stopping bot {bot_id}: {e}")
            return False, f"Failed to stop bot: {str(e)}"

    async def restart_bot(self, bot_id: str) -> tuple[bool, str]:
        await self.stop_bot(bot_id)
        await asyncio.sleep(1)
        return await self.start_bot(bot_id)

    def get_logs(self, bot_id: str, lines: int = 25) -> str:
        # Check in-memory buffer first
        if bot_id in self.log_buffers and self.log_buffers[bot_id]:
            recent = list(self.log_buffers[bot_id])[-lines:]
            return "\n".join(recent)

        # Fallback to reading file
        log_file = self.get_log_file_path(bot_id)
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    file_lines = f.readlines()
                    return "".join(file_lines[-lines:])
            except Exception as e:
                return f"Error reading log file: {e}"

        return "No logs generated yet."

    def is_running(self, bot_id: str) -> bool:
        process = self.active_processes.get(bot_id)
        return process is not None and process.returncode is None

    async def watchdog_loop(self):
        """Monitors running child processes and marks crashed ones."""
        while True:
            try:
                for bot_id, process in list(self.active_processes.items()):
                    if process.returncode is not None:
                        # Process exited
                        del self.active_processes[bot_id]
                        bot_data = database.get_bot(bot_id)
                        if bot_data and bot_data.get('auto_restart') and bot_data['status'] == 'RUNNING':
                            # Crash-loop guard: if a bot keeps dying, stop auto-restarting it.
                            now = time.monotonic()
                            hist = self.restart_history.setdefault(bot_id, deque(maxlen=20))
                            while hist and now - hist[0] > 120:
                                hist.popleft()
                            if len(hist) >= 5:
                                hist.clear()
                                database.update_bot_status(bot_id, "CRASHED")
                                logger.error(f"Bot {bot_id} is crash-looping (5+ restarts in <120s). Auto-restart disabled; marked CRASHED.")
                                continue
                            hist.append(now)
                            logger.warning(f"Bot {bot_id} exited with code {process.returncode}. Auto-restarting...")
                            database.update_bot_status(bot_id, "RESTARTING")
                            await asyncio.sleep(2)
                            await self.start_bot(bot_id)
                        else:
                            self.restart_history.pop(bot_id, None)
                            database.update_bot_status(bot_id, "CRASHED" if process.returncode != 0 else "STOPPED")
                            logger.info(f"Bot {bot_id} exited with status {process.returncode}.")
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
            await asyncio.sleep(5)

bot_manager = BotProcessManager()
