from kivy.app import App
from ui import ShiftTrackerRoot
from kivy.core.window import Window


class ShiftTrackerApp(App):
    def build(self):
        Window.set_icon("assets/tempicon.png")
        return ShiftTrackerRoot()

if __name__ == "__main__":
    ShiftTrackerApp().run()