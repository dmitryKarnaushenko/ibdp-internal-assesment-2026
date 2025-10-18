import os
import datetime
import calendar
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.graphics import Color, Rectangle
from kivy.core.window import Window  # Moved to top level import

import ocr_engine

# Ensure userdata folder exists for storing output files
os.makedirs("userdata", exist_ok=True)

# Define the application's color scheme using hex values
BG_COLOR = "#393E46"
TEXT_COLOR = "#DFD0B8"
BUTTON_COLOR = "#948979"

# Define colors for different shift types in calendar view using RGBA values (0-1 range)
SHIFT_COLORS = {
    "M": (1, 1, 0, 1),
    "T": (1, 0.6, 0, 1),
    "N": (0.2, 0.2, 0.6, 1)
}


# ---------- Home Screen ----------
class HomeScreen(Screen):
    """The main screen of the application that allows users to upload images,
    view parsed schedules, and see statistics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Root layout with background color
        # Using BoxLayout with vertical orientation for main content area
        self.root_layout = BoxLayout(orientation="vertical", padding=10, spacing=10)

        # Set up background color for the root layout
        self.root_layout.canvas.before.clear()
        with self.root_layout.canvas.before:
            Color(*self._hex_to_rgb(BG_COLOR))
            self.bg_rect = Rectangle(size=self.root_layout.size, pos=self.root_layout.pos)
            # Bind size and position changes to update the background
            self.root_layout.bind(size=self._update_bg, pos=self._update_bg)

        # Upload button - allows users to select an image file
        self.upload_button = Button(
            text="Upload Image",
            background_color=self._hex_to_rgb(BUTTON_COLOR),
            color=self._hex_to_rgb(TEXT_COLOR),
            size_hint=(1, 0.3),
            font_size=24,
            background_normal='',  # Remove default button style
        )
        # Bind button press to open file chooser
        self.upload_button.bind(on_press=self.open_filechooser)
        self.root_layout.add_widget(self.upload_button)

        # Add the root layout to the screen
        self.add_widget(self.root_layout)

        # Initialize instance variables
        self.ocr_text = ""  # Raw OCR output text
        self.parsed = None  # Parsed schedule data
        self.calendar_grid = None

    def _hex_to_rgb(self, hex_color):
        """Convert hex color string to kivy RGBA tuple (0-1 range)"""
        hex_color = hex_color.lstrip("#")  # Remove '#' if present
        # Convert each pair of hex digits to decimal and normalize to 0-1 range
        return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1,)

    def _update_bg(self, instance, value):
        """Update background rectangle when layout size or position changes"""
        self.bg_rect.size = instance.size
        self.bg_rect.pos = instance.pos

    def open_filechooser(self, instance):
        """Open a file chooser dialog to select an image file"""
        # Create file chooser with image filters
        chooser = FileChooserIconView(filters=["*.png", "*.jpg", "*.jpeg", "*.bmp"])

        # Create select and cancel buttons
        select_btn = Button(
            text="Select", size_hint_y=None, height=40,
            background_color=self._hex_to_rgb(BUTTON_COLOR),
            color=self._hex_to_rgb(TEXT_COLOR)
        )
        cancel_btn = Button(
            text="Cancel", size_hint_y=None, height=40,
            background_color=self._hex_to_rgb(BUTTON_COLOR),
            color=self._hex_to_rgb(TEXT_COLOR)
        )

        # Create layout for the popup
        layout = BoxLayout(orientation="vertical", padding=10)
        layout.add_widget(chooser)

        # Add buttons to a horizontal layout
        btns = BoxLayout(size_hint_y=None, height=40, spacing=10)
        btns.add_widget(select_btn)
        btns.add_widget(cancel_btn)
        layout.add_widget(btns)

        # Create and open the popup
        popup = Popup(title="Select Image", content=layout, size_hint=(0.9, 0.9))

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
        # Get raw OCR text from the image
        raw_text = ocr_engine.dump_raw_ocr(file_path)

        # Show popup with raw OCR output (capped at 2000 characters)
        popup = Popup(
            title="Raw OCR Output",
            content=Label(text=raw_text[:2000], color=self._hex_to_rgb(TEXT_COLOR)),
            size_hint=(0.9, 0.9)
        )
        popup.open()

        # Process image to extract structured data
        _, info, parsed = ocr_engine.process_image(file_path)
        self.ocr_text = info
        self.parsed = parsed

        # Save structured outputs if parsing was successful
        if parsed is not None:
            ocr_engine.save_outputs(parsed)

        # Save debug info to JSON file
        with open("userdata/debug_parsed.json", "w", encoding="utf-8") as f:
            import json
            json.dump(parsed, f, indent=2)

        # Reset layout to prepare for displaying parsed data
        self.root_layout.clear_widgets()

        # Create calendar view with 7 columns (for days of the week)
        self.calendar_grid = GridLayout(cols=7, spacing=4, size_hint=(1, 0.8))
        self.populate_calendar(parsed)
        self.root_layout.add_widget(self.calendar_grid)

        # Create bottom buttons for additional actions
        btns = BoxLayout(size_hint=(1, 0.2), spacing=10)

        # Statistics button
        self.stats_button = Button(
            text="View Stats",
            background_color=self._hex_to_rgb(BUTTON_COLOR),
            color=self._hex_to_rgb(TEXT_COLOR),
            background_normal=''
        )
        self.stats_button.bind(on_press=self.show_stats)

        # Back button to upload another image
        self.back_button = Button(
            text="Upload Another",
            background_color=self._hex_to_rgb(BUTTON_COLOR),
            color=self._hex_to_rgb(TEXT_COLOR),
            background_normal=''
        )
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
                text="No shifts parsed", color=self._hex_to_rgb(TEXT_COLOR)
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
            self.calendar_grid.add_widget(Label(text="", color=self._hex_to_rgb(TEXT_COLOR)))

        # Create calendar cells for each day of the month
        for d in range(1, num_days + 1):
            # Create container for day cell with fixed height
            cell_container = BoxLayout(
                orientation="vertical",
                size_hint_y=None,
                height=cell_height,
                padding=2
            )

            # Day number label (top section, 30% of cell height)
            day_label = Label(
                text=str(d),
                color=self._hex_to_rgb(TEXT_COLOR),
                size_hint_y=0.3,
                font_size='14sp'
            )
            cell_container.add_widget(day_label)

            # Container for shifts (bottom section, 70% of cell height)
            shifts_container = GridLayout(
                cols=1,
                size_hint_y=0.7,
                spacing=2
            )

            # Add colored blocks for each shift on this day
            for code in lookup.get(d, []):
                block = Label(
                    text=code,
                    color=(1, 1, 1, 1),  # white text
                    bold=True,
                    size_hint_y=None,
                    height=cell_height * 0.2  # Each shift takes 20% of cell height
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

    def show_stats(self, instance):
        """Show statistics popup with hours worked by shift type"""
        if not self.parsed or not self.parsed.get("records"):
            content = Label(text="No stats available", color=self._hex_to_rgb(TEXT_COLOR))
        else:
            # Calculate total hours by shift type
            counts = {}
            for rec in self.parsed["records"]:
                counts[rec["shift_type"]] = counts.get(rec["shift_type"], 0) + rec["hours"]

            # Format statistics string
            stats_str = "Hours worked:\n" + "\n".join([f"{k}: {v}" for k, v in counts.items()])
            content = Label(text=stats_str, color=self._hex_to_rgb(TEXT_COLOR))

        # Create and show statistics popup
        popup = Popup(
            title="Shift Stats",
            content=content,
            size_hint=(0.7, 0.7)
        )
        popup.open()

    def reset_ui(self):
        """Reset UI to initial state for uploading a new image"""
        self.root_layout.clear_widgets()

        # Recreate upload button
        self.upload_button = Button(
            text="Upload Image",
            background_color=self._hex_to_rgb(BUTTON_COLOR),
            color=self._hex_to_rgb(TEXT_COLOR),
            size_hint=(1, 0.3),
            font_size=24,
            background_normal=''
        )
        self.upload_button.bind(on_press=self.open_filechooser)
        self.root_layout.add_widget(self.upload_button)

        # Reset parsed data
        self.parsed = None


# ---------- Root Manager ----------
class ShiftTrackerRoot(ScreenManager):
    """The root screen manager for the application."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Add the home screen with identifier "home"
        self.add_widget(HomeScreen(name="home"))