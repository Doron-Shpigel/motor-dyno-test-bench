"""
Terminal User Interface (TUI) for motor-dyno-test-bench.

Pure Python curses-based interactive console interface for headless/low-spec systems
(Raspberry Pi, SSH sessions, non-X11 Linux). Exposes every dyno capability:
  - Real-time telemetry dashboard & stability monitor badge
  - Hardware relays & control mode switching
  - ASCII sparkline / history chart for torque vs target
  - Profile loading and manual test run execution
  - PID parameters tuning and EEPROM read/write
  - Torque calibration wizard
  - Integrated CSV logging
  - Resilient resizing and graceful exit
"""

from collections import deque
try:
    import curses
except (ImportError, ModuleNotFoundError):
    try:
        import windows_curses  # type: ignore # noqa: F401
        import curses
    except (ImportError, ModuleNotFoundError):
        curses = None
import math
from pathlib import Path
import time
from typing import Any, Callable

from modules.data_model import RunMode, RunState, Sample
from modules.engine import DynoEngine
from modules.transport import BaseTransport, MockTransport, SimulatedTransport, list_serial_ports


# Box drawing characters
BOX_TL = "┌"
BOX_TR = "┐"
BOX_BL = "└"
BOX_BR = "┘"
BOX_H = "─"
BOX_V = "│"
BOX_LT = "├"
BOX_RT = "┤"
BOX_TT = "┬"
BOX_BT = "┴"
BOX_CROSS = "┼"

# Color Pair IDs
COLOR_DEFAULT = 0
COLOR_CONNECTED = 1     # Green on default
COLOR_DISCONNECTED = 2  # Red on default
COLOR_WARNING = 3       # Yellow on default
COLOR_CYAN = 4          # Cyan on default
COLOR_MAGENTA = 5       # Magenta on default
COLOR_HEADER = 6        # White on Blue
COLOR_BADGE_STABLE = 7  # Black on Green


def get_color_pair(pair_id: int) -> int:
    """Safely return curses color pair, returning 0 if curses is not initialized or colors unsupported."""
    try:
        return curses.color_pair(pair_id)
    except Exception:
        return 0


def format_ascii_graph(
    samples: list[Sample],
    height: int,
    width: int,
) -> list[tuple[str, list[tuple[str, int]]]]:
    """
    Generate an ASCII history plot of measured torque vs target torque.

    Parameters
    ----------
    samples : list of Sample objects
    height : available rows for the plot (minimum 3)
    width : available total columns (including label)

    Returns
    -------
    list of (label_str, list of (char, color_pair_id)) for each row from top to bottom.
    """
    height = max(3, height)
    label_width = 7  # e.g. " 5.0┤ "
    plot_cols = max(5, width - label_width)

    # Use the most recent 'plot_cols' samples
    visible = samples[-plot_cols:] if len(samples) > plot_cols else list(samples)

    if visible:
        peak = max(
            max(s.torque_nm for s in visible),
            max(s.target_torque_nm for s in visible),
            1.0,
        )
        y_max = max(1.0, math.ceil(peak * 1.25 * 2.0) / 2.0)
    else:
        y_max = 5.0
    y_min = 0.0
    span = y_max - y_min if y_max > y_min else 1.0

    # Initialize grid: height rows x plot_cols columns
    grid = [[(" ", COLOR_DEFAULT) for _ in range(plot_cols)] for _ in range(height)]

    # Draw bottom horizontal axis baseline
    for c in range(plot_cols):
        grid[height - 1][c] = ("─", COLOR_DEFAULT)

    # Plot points (right-aligned oscilloscope style)
    if visible:
        offset = plot_cols - len(visible)
        for i, s in enumerate(visible):
            col_idx = offset + i
            if 0 <= col_idx < plot_cols:
                # Clamp torque values to [y_min, y_max]
                m_val = max(y_min, min(y_max, s.torque_nm))
                t_val = max(y_min, min(y_max, s.target_torque_nm))

                # Row indices (0 is top row, height-1 is bottom row)
                m_row = int(round((y_max - m_val) / span * (height - 1)))
                t_row = int(round((y_max - t_val) / span * (height - 1)))

                m_row = max(0, min(height - 1, m_row))
                t_row = max(0, min(height - 1, t_row))

                if m_row == t_row:
                    grid[m_row][col_idx] = ("X", COLOR_CONNECTED)  # Overlap / match
                else:
                    grid[t_row][col_idx] = ("-", COLOR_WARNING)    # Target setpoint
                    grid[m_row][col_idx] = ("*", COLOR_CYAN)       # Measured torque

    # Construct formatted lines with Y-axis labels
    result: list[tuple[str, list[tuple[str, int]]]] = []
    for r in range(height):
        y_val = y_max - (r / (height - 1)) * span
        if r == 0:
            label = f"{y_val:4.1f}┤ "
        elif r == height - 1:
            label = f"{y_val:4.1f}┴ "
        elif r == height // 2:
            label = f"{y_val:4.1f}┤ "
        else:
            label = "    │ "
        result.append((label, grid[r]))

    return result


class DynoTUI:
    """
    Curses-based Dyno Terminal User Interface.
    """

    def __init__(
        self,
        engine: DynoEngine | None = None,
        port: str = "",
        baud: int = 115200,
        demo_mode: bool = False,
        initial_profile: str | Path | None = None,
    ) -> None:
        self.demo_mode = demo_mode
        self.target_port = port
        self.target_baud = baud
        self.initial_profile = initial_profile

        # Create or attach engine
        if engine is not None:
            self.engine = engine
        else:
            if self.demo_mode:
                transport: BaseTransport = SimulatedTransport(port="DEMO_PORT")
            else:
                transport = None  # DynoEngine creates SerialTransport on connect
            self.engine = DynoEngine(transport=transport)

        # Telemetry & UI buffers
        self.log_messages: deque[tuple[str, str, str]] = deque(maxlen=100)
        self.sample_history: deque[Sample] = deque(maxlen=120)
        self._manual_preset_torque: float = 1.0
        self._running: bool = False
        self._prompt_active: bool = False
        self._status_text: str = "TUI Ready. Press [?] or review keys below."
        self._last_draw_time: float = 0.0

        # Subscribe to engine events
        self.engine.add_listener("on_status", self._handle_on_status)
        self.engine.add_listener("on_error", self._handle_on_error)
        self.engine.add_listener("on_telemetry", self._handle_on_telemetry)

        if self.demo_mode:
            self._handle_on_status("Initialized in DEMO / SIMULATION mode (SimulatedTransport active).")

    # ------------------------------------------------------------------
    # Engine Event Handlers
    # ------------------------------------------------------------------

    def _handle_on_status(self, msg: str) -> None:
        t_str = time.strftime("%H:%M:%S")
        self.log_messages.append((t_str, "INFO", str(msg)))
        self._status_text = str(msg)

    def _handle_on_error(self, msg: str) -> None:
        t_str = time.strftime("%H:%M:%S")
        self.log_messages.append((t_str, "ERROR", str(msg)))
        self._status_text = f"ERROR: {msg}"

    def _handle_on_telemetry(self, sample: Sample) -> None:
        self.sample_history.append(sample)

    # ------------------------------------------------------------------
    # Curses Setup & Teardown
    # ------------------------------------------------------------------

    def _init_curses(self, stdscr: Any) -> None:
        """Initialize curses environment, colors, and input settings."""
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        stdscr.nodelay(True)

        try:
            curses.curs_set(0)
        except Exception:
            pass

        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except Exception:
                pass

            curses.init_pair(COLOR_CONNECTED, curses.COLOR_GREEN, -1)
            curses.init_pair(COLOR_DISCONNECTED, curses.COLOR_RED, -1)
            curses.init_pair(COLOR_WARNING, curses.COLOR_YELLOW, -1)
            curses.init_pair(COLOR_CYAN, curses.COLOR_CYAN, -1)
            curses.init_pair(COLOR_MAGENTA, curses.COLOR_MAGENTA, -1)
            curses.init_pair(COLOR_HEADER, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(COLOR_BADGE_STABLE, curses.COLOR_BLACK, curses.COLOR_GREEN)

    # ------------------------------------------------------------------
    # Drawing Utilities
    # ------------------------------------------------------------------

    def safe_addstr(self, win: Any, y: int, x: int, text: str, attr: int = 0) -> None:
        """Safely write string to window without crashing on terminal bounds."""
        try:
            h, w = win.getmaxyx()
            if y < 0 or y >= h or x < 0 or x >= w:
                return
            avail = w - x
            if y == h - 1:
                avail = min(avail, w - x - 1)
            if avail <= 0:
                return
            win.addstr(y, x, str(text)[:avail], attr)
        except Exception:
            pass

    def draw_box(self, win: Any, y: int, x: int, h: int, w: int, title: str = "", attr: int = 0) -> None:
        """Draw an outline box with optional title header."""
        if h < 2 or w < 2:
            return
        top = BOX_TL + BOX_H * (w - 2) + BOX_TR
        if title:
            t = f" {title} "
            if len(t) < w - 4:
                top = BOX_TL + BOX_H + t + BOX_H * (w - 3 - len(t)) + BOX_TR

        self.safe_addstr(win, y, x, top, attr)
        for row in range(1, h - 1):
            self.safe_addstr(win, y + row, x, BOX_V, attr)
            self.safe_addstr(win, y + row, x + w - 1, BOX_V, attr)
        bottom = BOX_BL + BOX_H * (w - 2) + BOX_BR
        self.safe_addstr(win, y + h - 1, x, bottom, attr)

    # ------------------------------------------------------------------
    # Screen Rendering
    # ------------------------------------------------------------------

    def draw(self, stdscr: Any) -> None:
        """Render the complete dyno dashboard."""
        max_y, max_x = stdscr.getmaxyx()

        # Minimum size requirement check
        if max_y < 22 or max_x < 70:
            stdscr.erase()
            self.safe_addstr(
                stdscr,
                max(0, max_y // 2 - 1),
                max(0, (max_x - 30) // 2),
                "TERMINAL WINDOW TOO SMALL",
                curses.A_BOLD | get_color_pair(COLOR_DISCONNECTED),
            )
            self.safe_addstr(
                stdscr,
                max(0, max_y // 2),
                max(0, (max_x - 36) // 2),
                f"Current: {max_x}x{max_y} (Minimum: 80x24)",
                curses.A_NORMAL,
            )
            self.safe_addstr(
                stdscr,
                max(0, max_y // 2 + 1),
                max(0, (max_x - 30) // 2),
                "Resize window or press [Q] to quit",
                get_color_pair(COLOR_WARNING),
            )
            stdscr.refresh()
            return

        stdscr.erase()

        # 1. Header Banner (Rows 0-1)
        self.draw_header(stdscr, 0, max_x)

        # Layout metrics
        half_w = max_x // 2
        panel_h = 11

        # 2. Live Telemetry Panel (Rows 2 to 12, Left)
        self.draw_telemetry_panel(stdscr, 2, 0, panel_h, half_w)

        # 3. Controls & Hardware Panel (Rows 2 to 12, Right)
        self.draw_controls_panel(stdscr, 2, half_w, panel_h, max_x - half_w)

        # Middle / Lower sections
        footer_h = 2
        middle_y = 2 + panel_h
        avail_middle = max_y - middle_y - footer_h

        if avail_middle >= 8:
            graph_h = max(5, int(avail_middle * 0.55))
            log_h = avail_middle - graph_h
        else:
            graph_h = max(3, avail_middle // 2)
            log_h = max(2, avail_middle - graph_h)

        # 4. Real-Time ASCII Graph (middle_y to middle_y + graph_h)
        self.draw_graph_panel(stdscr, middle_y, 0, graph_h, max_x)

        # 5. Status & Message Log (middle_y + graph_h to max_y - footer_h)
        log_y = middle_y + graph_h
        self.draw_log_panel(stdscr, log_y, 0, log_h, max_x)

        # 6. Interactive Keybindings Bar (Bottom 2 rows)
        if not self._prompt_active:
            self.draw_footer(stdscr, max_y - footer_h, max_x)

        stdscr.refresh()

    def draw_header(self, stdscr: Any, y: int, w: int) -> None:
        """Render top title banner and system status indicators."""
        banner_attr = get_color_pair(COLOR_HEADER) | curses.A_BOLD

        # Background bar
        self.safe_addstr(stdscr, y, 0, " " * w, banner_attr)

        title = " MOTOR-DYNO TEST BENCH v2.0 "
        self.safe_addstr(stdscr, y, 1, title, banner_attr)

        # Port & Connection State
        port_name = (
            self.engine.transport.port
            if self.engine.transport and hasattr(self.engine.transport, "port")
            else (self.target_port or "NONE")
        )
        is_conn = self.engine.is_connected
        conn_text = "[CONNECTED]" if is_conn else "[DISCONNECTED]"
        conn_attr = (
            get_color_pair(COLOR_CONNECTED) | curses.A_BOLD
            if is_conn
            else get_color_pair(COLOR_DISCONNECTED) | curses.A_BOLD
        )

        mid_text = f"Port: {port_name} | "
        mid_x = max(len(title) + 2, (w - len(mid_text) - len(conn_text) - 25) // 2)
        self.safe_addstr(stdscr, y, mid_x, mid_text, banner_attr)
        self.safe_addstr(stdscr, y, mid_x + len(mid_text), conn_text, conn_attr)

        # Run State
        state_str = getattr(self.engine.state, "name", str(self.engine.state)).upper()
        mode_str = str(self.engine.control_mode).upper()
        right_text = f"Mode: {mode_str} | State: {state_str} "
        self.safe_addstr(stdscr, y, max(0, w - len(right_text) - 1), right_text, banner_attr)

        # Horizontal separator line
        self.safe_addstr(stdscr, y + 1, 0, BOX_H * w, get_color_pair(COLOR_CYAN))

    def draw_telemetry_panel(self, stdscr: Any, y: int, x: int, h: int, w: int) -> None:
        """Render Live Telemetry & stability badge."""
        self.draw_box(stdscr, y, x, h, w, "LIVE TELEMETRY", get_color_pair(COLOR_CYAN))

        # Measured & Target Torque
        meas_t = self.engine.current_torque
        targ_t = self.engine.target_torque
        self.safe_addstr(stdscr, y + 1, x + 2, f"Measured Torque: {meas_t:6.2f} N·m", curses.A_BOLD)
        self.safe_addstr(
            stdscr,
            y + 2,
            x + 2,
            f"Target Torque:   {targ_t:6.2f} N·m",
            get_color_pair(COLOR_MAGENTA) | curses.A_BOLD,
        )

        # Speed & DAC
        rpm = self.engine.current_rpm
        dac = self.engine.current_dac
        adc = self.engine.current_adc
        self.safe_addstr(stdscr, y + 3, x + 2, f"Speed:           {rpm:6.0f} RPM")
        self.safe_addstr(stdscr, y + 4, x + 2, f"DAC Output:      {dac:6d} / 4095")
        self.safe_addstr(stdscr, y + 5, x + 2, f"Speed ADC Raw:   {adc:6d} counts")

        # Stability status badge
        self.safe_addstr(stdscr, y + 6, x + 2, "Stability:")
        if self.engine.state == RunState.RUNNING:
            if self.engine.is_stable:
                badge = " [STABLE] "
                badge_attr = get_color_pair(COLOR_BADGE_STABLE) | curses.A_BOLD
            else:
                badge = " [WAITING] "
                badge_attr = get_color_pair(COLOR_WARNING) | curses.A_BOLD | curses.A_REVERSE
        else:
            badge = " [IDLE] "
            badge_attr = curses.A_DIM

        self.safe_addstr(stdscr, y + 6, x + 19, badge, badge_attr)

        # Run time & samples
        elapsed = self.engine.session.elapsed_seconds()
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        tenths = int((elapsed * 10) % 10)
        time_str = f"{mins:02d}:{secs:02d}.{tenths:01d}"
        sample_count = self.engine.session.sample_count()

        self.safe_addstr(stdscr, y + 7, x + 2, f"Elapsed Time:    {time_str:>8}")
        self.safe_addstr(stdscr, y + 8, x + 2, f"Samples Logged:  {sample_count:>8d}")

        # Profile Progress
        if self.engine.mode == RunMode.PROFILE:
            total = len(self.engine._plf.torques) if hasattr(self.engine, "_plf") and self.engine._plf.is_loaded() else 0
            cur_step = self.engine.current_step_idx + 1
            progress_str = f"Step {cur_step}/{total}"
        else:
            progress_str = "N/A (Manual)"
        self.safe_addstr(
            stdscr,
            y + 9,
            x + 2,
            f"Profile Progress: {progress_str}",
            get_color_pair(COLOR_CYAN),
        )

    def draw_controls_panel(self, stdscr: Any, y: int, x: int, h: int, w: int) -> None:
        """Render Hardware Relays, Control Mode, and PID Parameters."""
        self.draw_box(stdscr, y, x, h, w, "CONTROLS & HARDWARE", get_color_pair(COLOR_CYAN))

        # Control Mode
        mode_str = self.engine.control_mode.upper()
        self.safe_addstr(
            stdscr,
            y + 1,
            x + 2,
            f"Control Mode:     [O] {mode_str:<12}",
            curses.A_BOLD | get_color_pair(COLOR_WARNING),
        )

        # Manual Setpoint Preset
        self.safe_addstr(
            stdscr,
            y + 2,
            x + 2,
            f"Manual Setpoint:  {self._manual_preset_torque:6.2f} N·m  ([+] / [-])",
        )

        # Relays
        relays = self.engine.relays
        self.safe_addstr(stdscr, y + 3, x + 2, "Hardware Relays:")

        relay_defs = [
            ("1", "BRAKE", relays.get("BRAKE", False)),
            ("2", "SENSOR", relays.get("SENSOR", False)),
            ("3", "AUX", relays.get("AUX", False)),
        ]

        rx = x + 4
        for key_num, name, state in relay_defs:
            status = "[ON ]" if state else "[OFF]"
            attr = get_color_pair(COLOR_CONNECTED) | curses.A_BOLD if state else get_color_pair(COLOR_DISCONNECTED)
            self.safe_addstr(stdscr, y + 4 + (int(key_num) - 1), rx, f"[{key_num}] {name:<6}: ")
            self.safe_addstr(stdscr, y + 4 + (int(key_num) - 1), rx + 12, status, attr)

        # PID parameters
        kp, ki, kd = self.engine.stored_pid
        self.safe_addstr(stdscr, y + 7, x + 2, f"Active PID: [T]   Kp={kp:.1f} Ki={ki:.1f} Kd={kd:.1f}")

        # Calibration state
        self.safe_addstr(stdscr, y + 8, x + 2, "Torque Calib:     ")
        if getattr(self.engine, "_is_calibrating", False):
            self.safe_addstr(
                stdscr,
                y + 8,
                x + 20,
                "[ACTIVE - APPLY FORCE]",
                get_color_pair(COLOR_WARNING) | curses.A_BOLD,
            )
        else:
            self.safe_addstr(stdscr, y + 8, x + 20, "IDLE (Press [K] to start)", curses.A_DIM)

        # CSV Logging state
        log_open = self.engine._logger.is_open()
        log_text = "[LOGGING ACTIVE]" if log_open else "[IDLE]"
        log_attr = (
            get_color_pair(COLOR_CONNECTED) | curses.A_BOLD
            if log_open
            else curses.A_DIM
        )
        self.safe_addstr(stdscr, y + 9, x + 2, f"CSV Logger: [L]   {log_text}", log_attr)

    def draw_graph_panel(self, stdscr: Any, y: int, x: int, h: int, w: int) -> None:
        """Render Real-Time ASCII Torque vs Target visualizer."""
        title = "REAL-TIME TORQUE HISTORY (N·m)  [*] Measured  [-] Target  [X] Match"
        self.draw_box(stdscr, y, x, h, w, title, get_color_pair(COLOR_CYAN))

        plot_h = max(2, h - 2)
        plot_w = max(10, w - 2)

        lines = format_ascii_graph(list(self.sample_history), plot_h, plot_w)

        for row_idx, (label, cols) in enumerate(lines[:plot_h]):
            draw_y = y + 1 + row_idx
            # Draw axis label
            self.safe_addstr(stdscr, draw_y, x + 1, label, get_color_pair(COLOR_CYAN))
            # Draw plotted character points
            col_x = x + 1 + len(label)
            for ch, col_id in cols:
                attr = get_color_pair(col_id)
                if ch in ("*", "X"):
                    attr |= curses.A_BOLD
                self.safe_addstr(stdscr, draw_y, col_x, ch, attr)
                col_x += 1

    def draw_log_panel(self, stdscr: Any, y: int, x: int, h: int, w: int) -> None:
        """Render recent notifications and error messages."""
        self.draw_box(stdscr, y, x, h, w, "STATUS & EVENT LOG", get_color_pair(COLOR_CYAN))

        avail_rows = max(1, h - 2)
        recent_logs = list(self.log_messages)[-avail_rows:]

        for idx, (t_str, level, text) in enumerate(recent_logs):
            row_y = y + 1 + idx
            if level == "ERROR":
                attr = get_color_pair(COLOR_DISCONNECTED) | curses.A_BOLD
            elif level == "WARN":
                attr = get_color_pair(COLOR_WARNING) | curses.A_BOLD
            else:
                attr = curses.A_NORMAL

            log_line = f"[{t_str}] [{level:<5}] {text}"
            self.safe_addstr(stdscr, row_y, x + 2, log_line, attr)

    def draw_footer(self, stdscr: Any, y: int, w: int) -> None:
        """Render interactive keybindings bar."""
        line1_keys = [
            ("[C]", "Connect"),
            ("[M]", "Manual"),
            ("[+/-]", "Target"),
            ("[P]", "Profile"),
            ("[S]", "STOP"),
            ("[R]", "Reset"),
        ]
        line2_keys = [
            ("[O]", "Mode"),
            ("[1/2/3]", "Relays"),
            ("[T]", "PID"),
            ("[K]", "Calib"),
            ("[L]", "Log"),
            ("[Q]", "Quit"),
        ]

        def render_key_line(row_y: int, keys: list[tuple[str, str]]) -> None:
            curr_x = 1
            for k, desc in keys:
                self.safe_addstr(stdscr, row_y, curr_x, k, get_color_pair(COLOR_WARNING) | curses.A_BOLD)
                curr_x += len(k)
                text = f" {desc}  "
                self.safe_addstr(stdscr, row_y, curr_x, text, curses.A_NORMAL)
                curr_x += len(text)

        render_key_line(y, line1_keys)
        render_key_line(y + 1, line2_keys)

    # ------------------------------------------------------------------
    # Interactive Input Modal / Prompt
    # ------------------------------------------------------------------

    def prompt_input(self, stdscr: Any, prompt: str, default: str = "") -> str | None:
        """
        Display an interactive prompt on the bottom bar and read text input.
        Keeps background engine loops updating smoothly.
        """
        buffer: list[str] = []
        self._prompt_active = True
        try:
            curses.curs_set(1)
        except Exception:
            pass

        try:
            while self._running:
                max_y, max_x = stdscr.getmaxyx()
                self.draw(stdscr)

                # Draw bottom prompt bar (with horizontal scrolling if needed)
                full_prompt = f" >>> {prompt}{''.join(buffer)}"
                if len(full_prompt) >= max_x - 1:
                    prompt_text = "..." + full_prompt[-(max_x - 5):]
                else:
                    prompt_text = full_prompt

                self.safe_addstr(stdscr, max_y - 1, 0, " " * (max_x - 1), curses.A_REVERSE)
                self.safe_addstr(
                    stdscr,
                    max_y - 1,
                    0,
                    prompt_text,
                    curses.A_REVERSE | curses.A_BOLD | get_color_pair(COLOR_WARNING),
                )
                cursor_x = min(max_x - 2, len(prompt_text))
                try:
                    stdscr.move(max_y - 1, cursor_x)
                except Exception:
                    pass
                stdscr.refresh()

                try:
                    ch = stdscr.getch()
                except Exception:
                    ch = -1

                if ch == -1:
                    time.sleep(0.04)
                    continue

                if ch in (curses.KEY_ENTER, 10, 13):
                    val = "".join(buffer).strip()
                    return val if val else default
                elif ch in (27,):  # Escape cancels
                    return None
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buffer:
                        buffer.pop()
                elif ch == curses.KEY_RESIZE:
                    stdscr.erase()
                elif 32 <= ch <= 126:
                    if len(buffer) < 256:
                        buffer.append(chr(ch))
        finally:
            self._prompt_active = False
            try:
                curses.curs_set(0)
            except Exception:
                pass

        return None

    # ------------------------------------------------------------------
    # Key Action Dispatcher
    # ------------------------------------------------------------------

    def handle_key(self, ch: int, stdscr: Any = None) -> None:
        """Execute action associated with key press."""
        # Clean Quit
        if ch in (ord("q"), ord("Q")):
            self._running = False
            return

        # Emergency Stop
        if ch in (ord("s"), ord("S")):
            self.engine.stop()
            self._handle_on_status("EMERGENCY STOP executed. Relays opened and DAC zeroed.")
            return

        # Reset Dyno
        if ch in (ord("r"), ord("R")):
            self.engine.reset()
            self._handle_on_status("Dyno session reset to IDLE.")
            return

        # Target Setpoint adjustments (+ / -)
        if ch in (ord("+"), ord("=")):
            self.adjust_target_torque(0.1)
            return
        if ch in (ord("-"), ord("_")):
            self.adjust_target_torque(-0.1)
            return

        # Toggle Control Mode (Hybrid -> Closed -> Open)
        if ch in (ord("o"), ord("O")):
            self.toggle_control_mode()
            return

        # Toggle Relays (1: Brake, 2: Sensor, 3: Aux)
        if ch == ord("1"):
            self.toggle_relay("BRAKE")
            return
        if ch == ord("2"):
            self.toggle_relay("SENSOR")
            return
        if ch == ord("3"):
            self.toggle_relay("AUX")
            return

        # Torque Calibration (K)
        if ch in (ord("k"), ord("K")):
            self.toggle_calibration()
            return

        # Interactive prompts requiring stdscr
        if stdscr is not None:
            if ch in (ord("c"), ord("C")):
                self.interactive_connect(stdscr)
            elif ch in (ord("m"), ord("M")):
                self.interactive_manual_run(stdscr)
            elif ch in (ord("p"), ord("P")):
                self.interactive_profile_run(stdscr)
            elif ch in (ord("t"), ord("T")):
                self.interactive_pid_tuning(stdscr)
            elif ch in (ord("l"), ord("L")):
                self.interactive_logging(stdscr)

    def adjust_target_torque(self, delta: float) -> None:
        """Adjust target torque setpoint by delta N·m."""
        if self.engine.state == RunState.RUNNING and self.engine.mode == RunMode.MANUAL:
            new_target = max(0.0, round(self.engine.target_torque + delta, 2))
            self.engine.set_manual_torque(new_target)
            self._manual_preset_torque = new_target
        else:
            self._manual_preset_torque = max(0.0, round(self._manual_preset_torque + delta, 2))
            self._handle_on_status(f"Manual target setpoint preset: {self._manual_preset_torque:.2f} N·m")

    def toggle_control_mode(self) -> None:
        """Cycle control mode between hybrid, closed_loop, and open_loop."""
        modes = ["hybrid", "closed_loop", "open_loop"]
        current = self.engine.control_mode
        idx = modes.index(current) if current in modes else 0
        next_mode = modes[(idx + 1) % len(modes)]
        self.engine.control_mode = next_mode
        self._handle_on_status(f"Control mode changed to {next_mode.upper()}.")

    def toggle_relay(self, name: str) -> None:
        """Toggle specified relay state."""
        current = self.engine.relays.get(name.upper(), False)
        new_state = not current
        self.engine.set_relay(name, new_state)

    def toggle_calibration(self) -> None:
        """Toggle torque calibration start or finish."""
        if getattr(self.engine, "_is_calibrating", False):
            success = self.engine.finish_calibration()
            if success:
                self._handle_on_status("Torque calibration finished successfully.")
            else:
                self._handle_on_error("Torque calibration failed: insufficient force.")
        else:
            self.engine.start_calibration()
            self._handle_on_status("Calibration started: apply force now! Press [K] again to finish.")

    def interactive_connect(self, stdscr: Any) -> None:
        """Connect / Disconnect port prompt."""
        if self.engine.is_connected:
            resp = self.prompt_input(stdscr, "Disconnect current port? [y/N]: ", "N")
            if resp and resp.lower().startswith("y"):
                self.engine.disconnect()
                self._handle_on_status("Disconnected from port.")
        else:
            if self.demo_mode:
                self.engine.connect()
                self._handle_on_status("Connected to simulated transport.")
            else:
                ports = self.engine.list_ports()
                if ports:
                    ports_summary = ", ".join(f"[{i+1}]{p}" for i, p in enumerate(ports[:4]))
                    prompt = f"Ports ({ports_summary}). Select # or enter path [1]: "
                    resp = self.prompt_input(stdscr, prompt, "1")
                    if resp is not None:
                        resp = resp.strip()
                        if resp.isdigit() and 1 <= int(resp) <= len(ports):
                            chosen = ports[int(resp) - 1]
                        else:
                            chosen = resp if resp else ports[0]
                        try:
                            self.engine.connect(port=chosen, baud=self.target_baud)
                            self._handle_on_status(f"Connected to {chosen}.")
                        except Exception as exc:
                            self._handle_on_error(f"Cannot connect to {chosen}: {exc}")
                else:
                    resp = self.prompt_input(stdscr, "No ports detected. Enter port [/dev/ttyUSB0]: ", "/dev/ttyUSB0")
                    if resp:
                        try:
                            self.engine.connect(port=resp.strip(), baud=self.target_baud)
                            self._handle_on_status(f"Connected to {resp}.")
                        except Exception as exc:
                            self._handle_on_error(f"Cannot connect to {resp}: {exc}")

    def interactive_manual_run(self, stdscr: Any) -> None:
        """Prompt for torque setpoint and begin manual run."""
        prompt = f"Target torque in N·m [{self._manual_preset_torque:.2f}]: "
        resp = self.prompt_input(stdscr, prompt, f"{self._manual_preset_torque:.2f}")
        if resp is not None:
            try:
                val = float(resp)
                if val < 0.0 or val > 25.0:
                    self._handle_on_error("Torque setpoint must be between 0.0 and 25.0 N·m")
                else:
                    self._manual_preset_torque = val
                    self.engine.start_manual(val, mode=self.engine.control_mode)
            except ValueError:
                self._handle_on_error("Invalid number for torque setpoint.")

    def interactive_profile_run(self, stdscr: Any) -> None:
        """Prompt for profile CSV file path and start profile run."""
        default_path = "assets/load_test_template.csv"
        prompt = f"Profile CSV path [{default_path}]: "
        resp = self.prompt_input(stdscr, prompt, default_path)
        if resp is not None:
            p = Path(resp.strip())
            if not p.exists():
                self._handle_on_error(f"Profile CSV file not found: {p}")
            else:
                try:
                    self.engine.start_profile(p, mode=self.engine.control_mode)
                except Exception as exc:
                    self._handle_on_error(f"Failed to start profile: {exc}")

    def interactive_pid_tuning(self, stdscr: Any) -> None:
        """Prompt for new PID gains (Kp, Ki, Kd) and write to controller."""
        cur_p, cur_i, cur_d = self.engine.stored_pid
        default_val = f"{cur_p:.2f}, {cur_i:.2f}, {cur_d:.2f}"
        prompt = f"Enter Kp, Ki, Kd [{default_val}]: "
        resp = self.prompt_input(stdscr, prompt, default_val)
        if resp is not None:
            parts = [p.strip() for p in resp.split(",") if p.strip()]
            if len(parts) == 3:
                try:
                    kp, ki, kd = float(parts[0]), float(parts[1]), float(parts[2])
                    self.engine.set_pid(kp, ki, kd)
                    self._handle_on_status(f"Sent PID parameters: Kp={kp:.2f}, Ki={ki:.2f}, Kd={kd:.2f}")
                except ValueError as err:
                    self._handle_on_error(f"Invalid PID gains: {err}")
            else:
                self._handle_on_error("Must enter 3 comma-separated numbers: Kp, Ki, Kd")

    def interactive_logging(self, stdscr: Any) -> None:
        """Prompt to start explicit log file or flush active log."""
        if self.engine._logger.is_open():
            p = self.engine.stop_logging()
            self._handle_on_status(f"CSV log closed and saved to: {p}")
        else:
            prompt = "CSV log file path [temp_run.csv]: "
            resp = self.prompt_input(stdscr, prompt, "temp_run.csv")
            if resp is not None:
                p = self.engine.start_logging(resp.strip())
                self._handle_on_status(f"CSV logging active: {p}")

    # ------------------------------------------------------------------
    # Main Interactive Loop
    # ------------------------------------------------------------------

    def run(self, stdscr: Any) -> None:
        """Main curses execution loop."""
        try:
            self._init_curses(stdscr)
            self._running = True

            # Start engine autonomous background control loop
            self.engine.start_loop()

            # Connect transport if in demo mode or port was specified
            if self.demo_mode and not self.engine.is_connected:
                self.engine.connect()
            elif self.target_port and not self.engine.is_connected:
                try:
                    self.engine.connect(port=self.target_port, baud=self.target_baud)
                except Exception as exc:
                    self._handle_on_error(f"Initial connect failed: {exc}")

            # Auto-start initial profile if supplied
            if self.initial_profile:
                p = Path(self.initial_profile)
                if p.exists():
                    try:
                        self.engine.start_profile(p, mode=self.engine.control_mode)
                    except Exception as exc:
                        self._handle_on_error(f"Failed to start initial profile: {exc}")

            while self._running:
                self.draw(stdscr)
                try:
                    ch = stdscr.getch()
                except Exception:
                    ch = -1

                if ch != -1:
                    self.handle_key(ch, stdscr)

                time.sleep(0.04)

        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            try:
                self.engine.stop()
            except Exception:
                pass
            try:
                self.engine.stop_loop()
            except Exception:
                pass
            try:
                curses.curs_set(1)
            except Exception:
                pass
            try:
                curses.echo()
            except Exception:
                pass
            try:
                curses.endwin()
            except Exception:
                pass

    def start(self) -> None:
        """Launch the TUI within curses wrapper."""
        curses.wrapper(self.run)
