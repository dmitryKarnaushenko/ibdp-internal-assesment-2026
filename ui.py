import os
import datetime
import calendar
import time
from threading import Thread
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.progressbar import ProgressBar
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.graphics import Color, Rectangle, Ellipse, RoundedRectangle
from kivy.uix.widget import Widget
from kivy.core.window import Window  # Moved to top level import
from kivy.resources import resource_find

import ocr_engine

# Ensure userdata folder exists for storing output files
os.makedirs("userdata", exist_ok=True)

# Define the application's color scheme using hex values
# Dark navy-inspired canvas with lighter blue-grey controls and white text
BG_COLOR = "#0B192F"
CARD_COLOR = "#132643"
TEXT_COLOR = "#FFFFFF"
BUTTON_COLOR = "#3E5C88"
BUTTON_COLOR_ACTIVE = "#4F709F"
BUTTON_COLOR_DISABLED = "#1F2B3D"
DISABLED_TEXT_COLOR = "#8B9AAF"

# Define colors for different shift types in calendar view using RGBA values (0-1 range)
SHIFT_COLORS = {
    "M": (0.24, 0.62, 0.98, 1),
    "T": (0.17, 0.73, 0.82, 1),
    "N": (0.48, 0.43, 0.86, 1)
}

# Map human-readable shift types to consistent colors for statistics visuals
SHIFT_TYPE_COLORS = {
    shift_type: SHIFT_COLORS.get(code, (0.5, 0.5, 0.5, 1))
    for code, (shift_type, *_)
    in ocr_engine.SHIFT_MAP.items()
}


class PieChart(Widget):
    """Simple pie chart widget for visualizing shift distributions."""

    def __init__(self, data, color_lookup, **kwargs):
        super().__init__(**kwargs)
        self.data = data
        self.color_lookup = color_lookup
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def _redraw(self, *_, **__):
        """Redraw the pie based on current widget size and data."""
        self.canvas.clear()
        total = sum(self.data.values())
        if total <= 0:
            return

        angle_start = 0
        with self.canvas:
            for label, value in self.data.items():
                span = 360 * (value / total)
                Color(*self.color_lookup.get(label, (0.5, 0.5, 0.5, 1)))
                Ellipse(
                    pos=self.pos,
                    size=self.size,
                    angle_start=angle_start,
                    angle_end=angle_start + span,
                )
                angle_start += span


# ---------- Home Screen ----------
class HomeScreen(Screen):
    """The main screen of the application that allows users to upload images,
    view parsed schedules, and see statistics."""

    def __init__(self, use_prefab_data=False, **kwargs):
        super().__init__(**kwargs)

        self.use_prefab_data = use_prefab_data

        self.font_name = self._get_font()

        self.loading_event = None
        self.loading_start_time = None
        self.loading_duration = 12  # seconds
        self.progress_bar = None
        self.notification_events = []

        # Root layout with background color
        # Using BoxLayout with vertical orientation for main content area
        self.root_layout = BoxLayout(orientation="vertical", padding=12, spacing=12)

        Window.clearcolor = self._hex_to_rgb(BG_COLOR)

        # Set up background color for the root layout
        self.root_layout.canvas.before.clear()
        with self.root_layout.canvas.before:
            Color(*self._hex_to_rgb(BG_COLOR))
            self.bg_rect = Rectangle(size=self.root_layout.size, pos=self.root_layout.pos)
            # Bind size and position changes to update the background
            self.root_layout.bind(size=self._update_bg, pos=self._update_bg)

        # App title
        self.title_label = Label(
            text="Shift Tracker",
            color=self._hex_to_rgb(TEXT_COLOR),
            font_size="32sp",
            size_hint=(1, 0.18),
            bold=True,
            font_name=self.font_name,
        )

        # Initialize instance variables
        self.ocr_text = ""  # Raw OCR output text
        self.parsed = None  # Parsed schedule data
        self.calendar_grid = None
        self.persisted_parsed = None
        self.persisted_info = None

        # Add the root layout to the screen
        self.add_widget(self.root_layout)

        # Build the start menu and load any previously saved data
        self._load_persisted_data()
        self._build_start_menu()

    def _hex_to_rgb(self, hex_color):
        """Convert hex color string to kivy RGBA tuple (0-1 range)"""
        hex_color = hex_color.lstrip("#")  # Remove '#' if present
        # Convert each pair of hex digits to decimal and normalize to 0-1 range
        return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1,)

    def _get_font(self):
        """Resolve a Century Gothic font if available, falling back to default."""
        candidates = [
            "Century Gothic.ttf",
            "GOTHIC.TTF",
            "gothic.ttf",
            "CenturyGothic.ttf",
        ]
        for cand in candidates:
            path = resource_find(cand)
            if path:
                return path
        return "Roboto"

    def _create_button(self, text, size_hint=(1, None), height=56, font_size=20):
        """Create a rounded, themed button."""
        btn = Button(
            text=text,
            size_hint=size_hint,
            height=height,
            color=self._hex_to_rgb(TEXT_COLOR),
            background_color=(0, 0, 0, 0),
            background_normal='',
            background_down='',
            font_size=font_size,
            font_name=self.font_name,
        )
        btn.background_hex = BUTTON_COLOR
        btn.bind(size=self._round_button, pos=self._round_button, state=self._on_button_state)
        self._round_button(btn)
        return btn

    def _load_persisted_data(self):
        """Load previously saved shifts (or prefab data in demo mode)."""
        info, parsed = ocr_engine.load_saved_outputs(self.use_prefab_data)
        self.persisted_parsed = parsed if parsed else None
        self.persisted_info = info

    def _build_start_menu(self):
        """Render the landing view with options to view saved data or upload new."""
        self.root_layout.clear_widgets()
        self.root_layout.add_widget(self.title_label)

        status = self.persisted_info or ""
        status_label = Label(
            text=status,
            color=self._hex_to_rgb(TEXT_COLOR),
            font_size="16sp",
            halign="center",
            valign="middle",
            size_hint=(1, 0.26),
            text_size=(Window.width * 0.9, None),
            font_name=self.font_name,
        )
        self.root_layout.add_widget(status_label)

        btn_container = BoxLayout(orientation="vertical", spacing=12, size_hint=(1, 0.36))

        self.view_saved_button = self._create_button("View Saved Shifts", size_hint=(1, 0.5), font_size=22)
        self.view_saved_button.bind(on_press=self.show_saved_shifts)
        self.view_saved_button.disabled = self.persisted_parsed is None

        self.upload_button = self._create_button("Upload New Image", size_hint=(1, 0.5), font_size=22)
        self.upload_button.bind(on_press=self.open_filechooser)

        btn_container.add_widget(self.view_saved_button)
        btn_container.add_widget(self.upload_button)

        self.root_layout.add_widget(btn_container)

    def show_saved_shifts(self, *_):
        """Display the persisted shifts if available."""
        if not self.persisted_parsed:
            self._show_status_popup("No saved shifts available yet. Upload a new image to begin.")
            return

        self._display_results(self.persisted_info or "Saved shifts loaded.", self.persisted_parsed)

    def _show_status_popup(self, message):
        content = BoxLayout(orientation="vertical", padding=12, spacing=12)
        content.bind(size=self._tint_card, pos=self._tint_card)
        content.add_widget(Label(
            text=message,
            color=self._hex_to_rgb(TEXT_COLOR),
            halign="center",
            valign="middle",
            font_name=self.font_name,
            text_size=(Window.width * 0.6, None),
        ))

        close_btn = self._create_button("Close", size_hint=(1, None), height=48)
        content.add_widget(close_btn)

        popup = Popup(
            title="Shift Tracker",
            content=content,
            size_hint=(0.7, 0.4),
            background_color=self._hex_to_rgb(CARD_COLOR),
        )
        close_btn.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    def _round_button(self, instance, *_):
        """Apply a rounded rectangle background to a button."""
        instance.canvas.before.clear()
        is_disabled = getattr(instance, "disabled", False)
        bg_hex = (
            getattr(instance, "disabled_background_hex", BUTTON_COLOR_DISABLED)
            if is_disabled
            else getattr(instance, "background_hex", BUTTON_COLOR)
        )
        with instance.canvas.before:
            Color(*self._hex_to_rgb(bg_hex))
            RoundedRectangle(size=instance.size, pos=instance.pos, radius=[18, 18, 18, 18])

    def _on_button_state(self, instance, value):
        instance.background_hex = BUTTON_COLOR_ACTIVE if value == "down" else BUTTON_COLOR
        self._round_button(instance)

    def _update_bg(self, instance, value):
        """Update background rectangle when layout size or position changes"""
        self.bg_rect.size = instance.size
        self.bg_rect.pos = instance.pos

    def open_filechooser(self, instance):
        """Open a file chooser dialog to select an image file"""
        # Create file chooser with image filters
        chooser = FileChooserIconView(filters=["*.png", "*.jpg", "*.jpeg", "*.bmp"])

        # Create select and cancel buttons
        select_btn = self._create_button("Select", size_hint=(1, None), height=48)
        cancel_btn = self._create_button("Cancel", size_hint=(1, None), height=48)

        # Create layout for the popup
        layout = BoxLayout(orientation="vertical", padding=10)
        layout.add_widget(chooser)

        # Add buttons to a horizontal layout
        btns = BoxLayout(size_hint_y=None, height=60, spacing=10)
        btns.add_widget(select_btn)
        btns.add_widget(cancel_btn)
        layout.add_widget(btns)

        # Create and open the popup
        popup = Popup(
            title="Select Image",
            content=layout,
            size_hint=(0.9, 0.9),
            background_color=self._hex_to_rgb(CARD_COLOR),
        )

        def select_file(_):
            """Handle file selection"""
            if chooser.selection:
                path = chooser.selection[0]
                popup.dismiss()
                self.process_image(path)

        def cancel_file(_):
            """Handle cancel operation"""
            popup.dismiss()

        # Bind button actions
        select_btn.bind(on_press=select_file)
        cancel_btn.bind(on_press=cancel_file)
        popup.open()

    def process_image(self, file_path):
        """Process the selected image file through OCR and display results"""
        self._show_loading_state()

        self.loading_start_time = time.time()
        self.loading_event = Clock.schedule_interval(self._update_loading_progress, 0.1)

        Thread(target=self._process_image_background, args=(file_path,), daemon=True).start()

    def _process_image_background(self, file_path):
        """Handle OCR processing in a background thread and delay UI update for loading."""
        if self.use_prefab_data:
            parsed = ocr_engine.load_sample_parsed()
            if not parsed.get("records"):
                parsed = ocr_engine.FALLBACK_SAMPLE_PARSED
                info = "Loaded built-in prefab schedule (asset unavailable)."
            else:
                info = "Loaded prefab schedule for demo mode."
        else:
            _, info, parsed = ocr_engine.process_image(file_path)

        elapsed = time.time() - self.loading_start_time
        remaining = max(0, self.loading_duration - elapsed)
        if remaining:
            time.sleep(remaining)

        Clock.schedule_once(lambda dt: self._display_results(info, parsed), 0)

    def _show_loading_state(self):
        """Display a loading bar with a blank calendar beneath while processing."""
        self._clear_notifications()
        self.root_layout.clear_widgets()
        self.root_layout.add_widget(self.title_label)

        self.calendar_grid = GridLayout(cols=7, spacing=6, size_hint=(1, 0.7))
        self._populate_blank_calendar()
        self.root_layout.add_widget(self.calendar_grid)

        loader = BoxLayout(orientation="vertical", size_hint=(1, 0.2), spacing=8)
        loader.bind(size=self._tint_card, pos=self._tint_card)

        loader.add_widget(Label(
            text="Uploading image...",
            color=self._hex_to_rgb(TEXT_COLOR),
            font_size="18sp",
            halign="center",
            font_name=self.font_name,
        ))

        self.progress_bar = ProgressBar(max=100, value=0, size_hint=(1, None), height=24)
        loader.add_widget(self.progress_bar)
        self.root_layout.add_widget(loader)

    def _populate_blank_calendar(self):
        """Create a blank calendar grid while uploads are in progress."""
        placeholder_cells = 42  # 6 weeks x 7 days grid
        cell_height = Window.height * 0.1
        for _ in range(placeholder_cells):
            cell_container = BoxLayout(
                orientation="vertical",
                size_hint_y=None,
                height=cell_height,
                padding=4,
                spacing=4,
            )
            cell_container.bind(size=self._tint_card, pos=self._tint_card)
            cell_container.add_widget(Label(text="", color=self._hex_to_rgb(TEXT_COLOR), font_name=self.font_name))
            self.calendar_grid.add_widget(cell_container)

    def _update_loading_progress(self, *_):
        """Advance the progress bar over the loading duration."""
        if not self.progress_bar or not self.loading_start_time:
            return False

        elapsed = time.time() - self.loading_start_time
        progress = min((elapsed / self.loading_duration) * 100, 100)
        self.progress_bar.value = progress
        return progress < 100

    def _display_results(self, info, parsed):
        """Render OCR results after loading completes."""
        if self.loading_event:
            self.loading_event.cancel()
            self.loading_event = None
        if self.progress_bar:
            self.progress_bar.value = 100

        self.ocr_text = info
        self.parsed = parsed
        self.persisted_parsed = parsed
        self.persisted_info = info or "Saved shifts loaded."

        # Save structured outputs if parsing was successful
        if parsed is not None:
            ocr_engine.save_outputs(parsed)

        self._schedule_shift_notifications()

        # Save debug info to JSON file
        with open("userdata/debug_parsed.json", "w", encoding="utf-8") as f:
            import json
            json.dump(parsed, f, indent=2)

        # Reset layout to prepare for displaying parsed data
        self.root_layout.clear_widgets()

        # Re-add title above results
        self.root_layout.add_widget(self.title_label)

        # Create calendar view with 7 columns (for days of the week)
        self.calendar_grid = GridLayout(cols=7, spacing=6, size_hint=(1, 0.7))
        self.populate_calendar(parsed)
        self.root_layout.add_widget(self.calendar_grid)

        # Create bottom buttons for additional actions
        btns = BoxLayout(size_hint=(1, 0.18), spacing=12)

        # Statistics button
        self.stats_button = self._create_button("View Stats")
        self.stats_button.bind(on_press=self.show_stats)

        # Back button to upload another image
        self.back_button = self._create_button("Upload Another")
        self.back_button.bind(on_press=lambda _: self.reset_ui())

        # Add buttons to layout
        btns.add_widget(self.stats_button)
        btns.add_widget(self.back_button)
        self.root_layout.add_widget(btns)

    def populate_calendar(self, parsed):
        """Populate the calendar view with parsed shift data"""
        # Clear any existing widgets
        self.calendar_grid.clear_widgets()

        # Handle case where no data was parsed
        if not parsed or not parsed.get("records"):
            self.calendar_grid.add_widget(Label(
                text="No shifts parsed",
                color=self._hex_to_rgb(TEXT_COLOR),
                font_name=self.font_name,
            ))
            return

        year, month = parsed["year"], parsed["month"]

        # Calculate the number of days in the month
        num_days = calendar.monthrange(year, month)[1]

        # Build lookup dictionary: day -> list of shift codes
        lookup = {}
        for r in parsed["records"]:
            try:
                # Extract day from date string (format: YYYY-MM-DD)
                day = int(r["date"].split("-")[2])
                lookup.setdefault(day, []).append(r["shift_code"])
            except (IndexError, ValueError):
                continue  # Skip invalid date formats

        # Calculate cell height based on screen size (12% of window height)
        cell_height = Window.height * 0.12  # Now using the imported Window

        # Pad calendar to align first day with correct weekday
        first_day = datetime.date(year, month, 1)
        start_weekday = first_day.weekday()  # Monday=0, Sunday=6
        for _ in range(start_weekday):
            self.calendar_grid.add_widget(Label(text="", color=self._hex_to_rgb(TEXT_COLOR), font_name=self.font_name))

        # Create calendar cells for each day of the month
        for d in range(1, num_days + 1):
            # Create container for day cell with fixed height
            cell_container = BoxLayout(
                orientation="vertical",
                size_hint_y=None,
                height=cell_height,
                padding=4,
                spacing=4,
            )
            cell_container.bind(size=self._tint_card, pos=self._tint_card)

            # Day number label (top section, 30% of cell height)
            day_label = Label(
                text=str(d),
                color=self._hex_to_rgb(TEXT_COLOR),
                size_hint_y=0.3,
                font_size='14sp',
                font_name=self.font_name,
            )
            cell_container.add_widget(day_label)

            # Container for shifts (bottom section, 70% of cell height)
            shifts_container = GridLayout(
                cols=1,
                size_hint_y=0.7,
                spacing=3
            )

            # Add colored blocks for each shift on this day
            for code in lookup.get(d, []):
                block = Label(
                    text=code,
                    color=(1, 1, 1, 1),  # white text
                    bold=True,
                    size_hint_y=None,
                    height=cell_height * 0.2,  # Each shift takes 20% of cell height
                    font_name=self.font_name,
                )
                # Draw colored background based on shift type
                block.bind(size=self._update_bg_rect, pos=self._update_bg_rect)
                with block.canvas.before:
                    Color(*SHIFT_COLORS.get(code, (0.5, 0.5, 0.5, 1)))  # Default to gray
                    block.bg = Rectangle(size=block.size, pos=block.pos)
                shifts_container.add_widget(block)

            # Add shifts container to cell
            cell_container.add_widget(shifts_container)
            # Add cell to calendar grid
            self.calendar_grid.add_widget(cell_container)

    def _update_bg_rect(self, instance, value):
        """Update background rectangle for shift blocks when size/position changes"""
        if hasattr(instance, "bg"):
            instance.bg.size = instance.size
            instance.bg.pos = instance.pos

    def _tint_card(self, instance, *_):
        """Add a subtle rounded card background behind a widget."""
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(*self._hex_to_rgb(CARD_COLOR))
            RoundedRectangle(size=instance.size, pos=instance.pos, radius=[12, 12, 12, 12])

    def show_stats(self, instance):
        """Show statistics popup with hours worked by shift type"""
        if not self.parsed or not self.parsed.get("records"):
            content = Label(
                text="No stats available",
                color=self._hex_to_rgb(TEXT_COLOR),
                font_name=self.font_name,
            )
        else:
            counts = {}
            for rec in self.parsed["records"]:
                counts[rec["shift_type"]] = counts.get(rec["shift_type"], 0) + rec["hours"]

            content = BoxLayout(orientation="vertical", spacing=12, padding=12)
            content.bind(size=self._tint_card, pos=self._tint_card)

            total_hours = sum(counts.values())
            total_shifts = len(self.parsed["records"])
            summary = Label(
                text=f"Total hours: {total_hours:.1f}\nTotal shifts: {total_shifts}",
                color=self._hex_to_rgb(TEXT_COLOR),
                font_size="18sp",
                halign="center",
                valign="middle",
                font_name=self.font_name,
            )
            content.add_widget(summary)

            pie = PieChart(counts, SHIFT_TYPE_COLORS, size_hint=(1, 0.6))
            content.add_widget(pie)

            legend = GridLayout(cols=1, size_hint=(1, 0.4), spacing=8)
            total_hours = total_hours or 1
            for shift, hours in counts.items():
                pct = (hours / total_hours) * 100
                row = BoxLayout(orientation="horizontal", spacing=8)

                swatch = Widget(size_hint=(0.15, 1))
                swatch.bind(size=self._update_bg_rect, pos=self._update_bg_rect)
                with swatch.canvas.before:
                    Color(*SHIFT_TYPE_COLORS.get(shift, (0.5, 0.5, 0.5, 1)))
                    swatch.bg = Rectangle(size=swatch.size, pos=swatch.pos)

                row.add_widget(swatch)
                row.add_widget(Label(
                    text=f"{shift}: {hours:.1f}h ({pct:.0f}%)",
                    color=self._hex_to_rgb(TEXT_COLOR),
                    halign="left",
                    valign="middle",
                    font_name=self.font_name,
                ))
                legend.add_widget(row)

            content.add_widget(legend)

        popup = Popup(
            title="Shift Stats",
            content=content,
            size_hint=(0.75, 0.75),
            background_color=self._hex_to_rgb(CARD_COLOR),
        )
        popup.open()

    def reset_ui(self):
        """Reset UI to initial state for uploading a new image"""
        self._clear_notifications()
        self._load_persisted_data()
        self._build_start_menu()

    def _clear_notifications(self):
        """Cancel any scheduled shift notifications."""
        for event in self.notification_events:
            try:
                event.cancel()
            except Exception:
                pass
        self.notification_events.clear()

    def _schedule_shift_notifications(self):
        """Schedule in-app reminders 45 minutes before each shift starts."""
        self._clear_notifications()

        if not self.parsed or not self.parsed.get("records"):
            return

        now = datetime.datetime.now()
        for record in self.parsed["records"]:
            date_str = record.get("date")
            shift_code = record.get("shift_code")
            if not date_str or shift_code not in ocr_engine.SHIFT_MAP:
                continue

            try:
                shift_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            start_hour = ocr_engine.SHIFT_MAP[shift_code][1]
            start_dt = datetime.datetime.combine(shift_date, datetime.time(hour=start_hour))
            notify_at = start_dt - datetime.timedelta(minutes=45)
            delay = (notify_at - now).total_seconds()
            if delay <= 0:
                continue

            event = Clock.schedule_once(
                lambda *_dt, rec=record, starts=start_dt: self._show_notification(rec, starts), delay
            )
            self.notification_events.append(event)

    def _show_notification(self, record, start_dt):
        """Display a dismissible popup for an upcoming shift."""
        shift_label = record.get("shift_type") or ocr_engine.SHIFT_MAP.get(record.get("shift_code"), ("Shift",))[0]
        minutes_remaining = max(int((start_dt - datetime.datetime.now()).total_seconds() // 60), 0)
        msg = f"{shift_label} shift at {start_dt.strftime('%Y-%m-%d %H:%M')} starts in {minutes_remaining} minutes."

        content = BoxLayout(orientation="vertical", padding=12, spacing=12)
        content.bind(size=self._tint_card, pos=self._tint_card)
        content.add_widget(Label(
            text=msg,
            color=self._hex_to_rgb(TEXT_COLOR),
            halign="center",
            valign="middle",
            font_name=self.font_name,
            text_size=(Window.width * 0.6, None),
        ))

        dismiss_btn = self._create_button("Dismiss", size_hint=(1, None), height=48)
        content.add_widget(dismiss_btn)

        popup = Popup(
            title="Shift Reminder",
            content=content,
            size_hint=(0.7, 0.4),
            background_color=self._hex_to_rgb(CARD_COLOR),
        )

        dismiss_btn.bind(on_press=lambda *_: popup.dismiss())
        popup.open()


# ---------- Root Manager ----------
class ShiftTrackerRoot(ScreenManager):
    """The root screen manager for the application."""

    def __init__(self, use_prefab_data=False, **kwargs):
        super().__init__(**kwargs)
        # Add the home screen with identifier "home"
        self.add_widget(HomeScreen(name="home", use_prefab_data=use_prefab_data))


