from kivy.app import App
from kivy.core.window import Window

from ui import ShiftTrackerRoot


class PrefabShiftTrackerApp(App):
    """Demo app that always displays prefab calendar/stats outputs."""

    def build(self):
        Window.set_icon("assets/tempicon.png")
        return ShiftTrackerRoot(use_prefab_data=True)


if __name__ == "__main__":
    PrefabShiftTrackerApp().run()
