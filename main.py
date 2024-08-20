import datetime
import json
import os
import shutil
import sys
import subprocess
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QComboBox,
    QPushButton,
    QMessageBox,
)
from enum import Enum
from PyQt5.QtCore import Qt
from enum import Enum
from pydantic import ValidationError
from pydantic import ValidationError
from server_config_model import RootConfig, ComputerTypeEnum, load_config


class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        self.root_config: RootConfig = load_config()
        self.init_ui()
        self.selected_type = None
        # self.set_prev_setting()

    def init_ui(self):
        layout = QVBoxLayout()
        self.config_dropdown = QComboBox()

        config_options = [
            (computer_type.value, computer_type) for computer_type in ComputerTypeEnum
        ]
        current_config_type = self.root_config.config_type

        for text, enum_value in config_options:
            self.config_dropdown.addItem(text, enum_value)
            if current_config_type.value == enum_value:
                print(text, "같다요", enum_value)
                self.config_dropdown.setCurrentText(text)

        apply_button = QPushButton("Apply and Launch")
        apply_button.clicked.connect(self.apply_and_launch)

        layout.addWidget(self.config_dropdown)
        layout.addWidget(apply_button)
        self.setLayout(layout)
        self.setWindowTitle("Config Selector")
        self.show()

    def apply_and_launch(self):
        from server_config_model import ExecuteFileMap

        selected_type: Enum = self.config_dropdown.currentData()
        if selected_type != self.root_config.config_type:
            reply = QMessageBox.question(
                self,
                "Save Confirmation",
                "The configuration has changed. Do you want to save it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.root_config.config_type = selected_type
                save_config(self.root_config)
                subprocess.Popen([sys.executable, ExecuteFileMap[selected_type.value]])
        else:
            subprocess.Popen([sys.executable, ExecuteFileMap[selected_type.value]])
        self.close()


def backup_config():
    """Backup the aiofarm_config.json file to the aiofarm_config_backup directory."""
    home_dir = os.path.expanduser("~")
    source_file = os.path.join(home_dir, "aiofarm_config.json")
    project_file = "pyproject.toml"
    backup_dir = os.path.join(home_dir, "aiofarm_config_backup")

    # Create backup directory if it doesn't exist
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    # Generate a unique backup file name with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"aiofarm_config_{timestamp}.json")

    if os.path.exists(source_file):
        shutil.copy2(source_file, backup_file)
        print(f"Backup successful: {backup_file}")
    else:
        print(f"Source file does not exist: {source_file}")


def save_config(config: RootConfig):
    config = RootConfig(**config.model_dump())
    try:
        with open(os.path.expanduser("~/aiofarm_config.json"), "w") as f:
            json.dump(config.model_dump(), f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


def load_config():
    """Load settings from a JSON file and return a Config object."""
    try:
        with open(os.path.expanduser("~/aiofarm_config.json"), "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error saving config: {e}")
        data = {}
    config = RootConfig.model_validate(data)
    print("config", config)
    return config


def main():
    app = QApplication(sys.argv)
    main_app = MainApp()
    sys.exit(app.exec_())


if __name__ == "__main__":
    backup_config()
    main()
