import importlib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading

import serial.tools.list_ports
import toml
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QIntValidator, QKeyEvent, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    qApp,
)
from server_config_model import (
    EncodingEnum,
    FormatEnum,
    RootConfig,
    ServerConfig,
    backup_config,
    load_server_root_config,
    save_config,
)


class LineCountTab(QWidget):
    def __init__(self, parent=None, tab_widget=None):
        super(LineCountTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        line_layout = QHBoxLayout()
        self.label = QLabel("1. 라인 개수 입력")
        self.line_edit = QLineEdit()
        line_layout.addWidget(self.label)
        line_layout.addWidget(self.line_edit)
        self.line_edit.setValidator(QIntValidator())  # Allow only integers

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.on_next)
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.next_button)

        layout.addLayout(line_layout)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        self.line_edit.setFocus()

    def on_next(self):
        line_count = self.line_edit.text()
        if line_count:
            self.save_line_count(int(line_count))
            current_index = self.tab_widget.currentIndex()
            self.tab_widget.setTabEnabled(current_index + 1, True)
            self.tab_widget.setCurrentIndex(current_index + 1)

    def save_line_count(self, line_count):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        if config is not None:
            config.program_config.line_count = line_count
            save_config(root_config)


class UploadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload to Arduino")
        self.setGeometry(300, 300, 400, 200)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        self.port_combo = QComboBox(self)
        self.refreshPorts()

        self.refresh_button = QPushButton("포트 새로 고침", self)
        self.refresh_button.clicked.connect(self.refreshPorts)

        self.upload_button = QPushButton("선택 포트에 업로드", self)
        self.upload_button.clicked.connect(self.uploadToSelectedPort)

        layout.addWidget(QLabel("Select Port:"))
        layout.addWidget(self.port_combo)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.upload_button)

        self.setLayout(layout)

    def refreshPorts(self):
        """Refresh the list of available serial ports."""
        self.port_combo.clear()
        ports = list(serial.tools.list_ports.comports())
        port_names = [port.device for port in ports]
        self.port_combo.addItems(port_names)
        if not port_names:
            QMessageBox.warning(
                self,
                "No Ports",
                "No serial ports found. Please check your connections.",
            )

    def uploadToSelectedPort(self):
        """Trigger the Arduino upload process."""
        selected_port = self.port_combo.currentText()
        if selected_port:
            QMessageBox.information(self, "Upload", f"Uploading to {selected_port}...")
            # Here you should integrate the actual upload logic
            # For example:
            # subprocess.run(["arduino-cli", "upload", "-p", selected_port, "--fqbn", "arduino:avr:mega", "your_sketch.ino"])
        else:
            QMessageBox.warning(self, "No Selection", "Please select a port first.")


class CustomLineEdit(QLineEdit):
    def keyPressEvent(self, event: QKeyEvent):
        # 입력된 키가 한글인지 확인
        text = event.text()
        if text and ord(text[0]) >= 0xAC00 and ord(text[0]) <= 0xD7A3:
            # 한글 입력 시 경고창 표시
            QMessageBox.warning(self, "입력 오류", "한글은 입력할 수 없습니다.")
            return  # 한글 입력을 무시
        # 한글이 아니면 기본 동작 수행
        super().keyPressEvent(event)


class SerialTestTab(QWidget):
    def __init__(self, parent=None, tab_widget=None):
        super(SerialTestTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.serial_connection = None
        self.write_serial_connection = None
        self.initUI()
        self.process_running = False

    def initUI(self):
        layout = QVBoxLayout()

        self.label = QLabel(
            "<h1>시리얼 테스트</h1>"
            "<h3><b>내부 시리얼</b> 선의 정상 여부를 확인하는 작업</h3>"
        )
        layout.addWidget(self.label)

        self.message_label = QLabel("읽기 확인용 메시지:")
        self.message_edit = QLineEdit()

        self.message_edit.textChanged.connect(self.change_serial_test_message)

        layout.addWidget(self.message_label)
        layout.addWidget(self.message_edit)

        self.baudrate_label = QLabel("읽기 확인용 보드레이트:")
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        layout.addWidget(self.baudrate_label)
        layout.addWidget(self.baudrate_combo)

        self.upload_button = QPushButton("읽기 확인용 Arduino 업로드")
        self.upload_button.setStyleSheet(
            """
            QPushButton {
                font-weight: bold;      /* 텍스트 굵게 */
            }
        """
        )
        self.upload_button.clicked.connect(self.upload_to_arduino)
        serial_upload_btn_layout = QHBoxLayout()
        serial_upload_btn_layout.addWidget(self.upload_button)
        layout.addLayout(serial_upload_btn_layout)

        self.port_label = QLabel(
            "<p>시리얼 연결 확인.(j1c.exe를 사용해서 확인도 가능)</p>"
        )
        self.port_combo = QComboBox()
        layout.addWidget(self.port_label)
        layout.addWidget(self.port_combo)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_serial)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_serial)
        self.disconnect_button.setEnabled(False)

        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_serial)

        self.port_refresh_button = QPushButton("Refresh")  # self.dis
        self.port_refresh_button.clicked.connect(self.refresh_serial)

        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.on_prev)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.on_next)

        button_layout = QHBoxLayout()
        serial_btn_layout = QHBoxLayout()

        button_layout.addStretch(1)
        button_layout.addWidget(self.prev_button)
        button_layout.addWidget(self.next_button)

        serial_btn_layout.addWidget(self.connect_button)
        serial_btn_layout.addWidget(self.disconnect_button)
        serial_btn_layout.addWidget(self.port_refresh_button)

        layout.addLayout(serial_btn_layout)

        layout.addStretch(1)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        self.write_port_label = QLabel(
            "<h3><b>외부 시리얼</b> 선의 정상 여부를 확인하는 작업(메시지 쓰기)</h3>"
            "쓰기 확인용 포트"
        )
        self.write_port_combo = QComboBox()
        layout.addWidget(self.write_port_label)
        layout.addWidget(self.write_port_combo)

        self.write_baudrate_label = QLabel("쓰기 확인용 보드레이트")
        self.write_baudrate_combo = QComboBox()
        self.write_baudrate_combo.addItems(
            ["9600", "19200", "38400", "57600", "115200"]
        )

        layout.addWidget(self.write_baudrate_label)
        layout.addWidget(self.write_baudrate_combo)

        self.write_message_label = QLabel("Enter Sending Message:")
        self.write_message_edit = QLineEdit()
        layout.addWidget(self.write_message_label)
        layout.addWidget(self.write_message_edit)

        self.encoder_label = QLabel("Encoder:")
        self.encoder_combo = QComboBox()
        # 예시로 사용할 수 있는 인코더 옵션 추가 (ASCII, UTF-8, UTF-16 등)
        # self.encoder_combo.addItems(
        #     ["ASCII", "UTF-8", "UTF-16", "ISO-8859-1", "UTF-32"]
        # )
        self.encoder_combo.addItems([e.value for e in EncodingEnum])

        layout.addWidget(self.encoder_label)
        layout.addWidget(self.encoder_combo)

        # Format Label and ComboBox
        self.format_label = QLabel("Format:")
        self.format_combo = QComboBox()
        self.format_combo.addItems([f.value for f in FormatEnum])
        # 예시로 사용할 수 있는 포맷 옵션 추가 (STX/ETX, CRLF 등)
        # self.format_combo.addItems(["STX/ETX", "CRLF", "LF", "CR", "None"])
        layout.addWidget(self.format_label)
        layout.addWidget(self.format_combo)

        self.update_port_list()

        self.write_button = QPushButton("Write Message to Serial")
        self.write_button.clicked.connect(self.write_serial_message)
        layout.addWidget(self.write_button)

        self.setLayout(layout)

        layout.addLayout(button_layout)

    def change_serial_test_message(self, value):
        pattern = re.compile("[ㄱ-ㅎ가-힣]+")
        korean = pattern.findall(value)
        if korean:
            self.message_edit.setText(value[:-1])
            QMessageBox.warning(self, "입력 오류", "한글은 입력할 수 없습니다.")

    def update_port_list(self):
        self.port_combo.clear()
        self.write_port_combo.clear()
        ports = list(serial.tools.list_ports.comports())
        port_names = [port.device for port in ports]
        self.port_combo.addItems(port_names)
        self.write_port_combo.addItems(port_names)

    def connect_serial(self):
        port = self.port_combo.currentText()
        baudrate = int(self.baudrate_combo.currentText())
        try:
            self.serial_connection = serial.Serial(port, baudrate, timeout=1)
            self.disconnect_button.setEnabled(True)
            self.connect_button.setEnabled(False)
            self.text_edit.append(f"Connected to {port} at {baudrate} baud.")
            self.start_reading_thread()
        except serial.SerialException as e:
            QMessageBox.critical(self, "Connection Error", f"Failed to connect: {e}")

    def connect_write_serial(self):
        port = self.write_port_combo.currentText()
        baudrate = int(self.write_baudrate_combo.currentText())
        try:
            self.write_serial_connection = serial.Serial(port, baudrate, timeout=1)
            print(self.write_serial_connection, port, baudrate)
            self.disconnect_button.setEnabled(True)
            self.connect_button.setEnabled(False)
            self.text_edit.append(f"Connected to {port} at {baudrate} baud.")
            self.start_reading_thread()
        except serial.SerialException as e:
            QMessageBox.critical(self, "Connection Error", f"Failed to connect: {e}")

    def refresh_serial(self):
        self.disconnect_serial()
        self.update_port_list()
        self.disconnect_button.setEnabled(False)

    def disconnect_serial(self):
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            self.disconnect_button.setEnabled(False)
            self.connect_button.setEnabled(True)
            self.text_edit.append("Disconnected.")

    def write_serial_message(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        port = self.write_port_combo.currentText()
        baudrate = int(self.write_baudrate_combo.currentText())
        selected_encoder = self.encoder_combo.currentText()
        message = self.write_message_edit.text()
        selected_format = self.format_combo.currentText()
        try:
            if not self.validate_serial_connection():
                return

            encoded_message = self.get_encoded_message()
            if not encoded_message:
                return

            formatted_message = self.format_message(encoded_message)
            self.write_serial_connection.write(formatted_message)
            QMessageBox.information(
                self, "Success", f"Message sent successfully. {formatted_message}"
            )
        except serial.SerialException as e:
            QMessageBox.critical(self, "Write Error", f"Failed to write to serial: {e}")
        else:
            config.serial_config.baudrate = baudrate
            config.serial_config.test_message_encode_type = EncodingEnum(
                selected_encoder
            )
            config.serial_config.test_message_format_type = FormatEnum(selected_format)
            config.serial_config.test_message_to_sorter = message
            save_config(root_config=root_config)
        finally:
            if self.write_serial_connection.is_open:
                self.write_serial_connection.close()

    def validate_serial_connection(self):
        # if self.serial_connection is None or not self.serial_connection.is_open:
        #     QMessageBox.critical(self, "Error", "Serial port is not connected.")
        #     return False
        # return True
        port = self.write_port_combo.currentText()
        baudrate = int(self.write_baudrate_combo.currentText())
        try:
            self.write_serial_connection = serial.Serial(
                port=port, baudrate=baudrate, timeout=1
            )
            print(self.write_serial_connection, port, baudrate)
            return True
        except serial.SerialException as e:
            QMessageBox.critical(self, "Connection Error", f"Failed to connect: {e}")
        return False

    def upload_to_arduino(self):
        self.dialog = UploadDialog(self)
        if self.dialog.exec_() == QDialog.Accepted:
            print("Upload completed or cancelled")

    def create_arduino_sketch(self, message, baudrate):
        arduino_code = f"""
        const char* message = "{message}";
        const int pins[] = {{30, 31, 32, 33, 34, 35, 36, 37}};
        const int numPins = sizeof(pins) / sizeof(pins[0]);
        unsigned long previousMillis = 0;
        const long interval = 300;  // 10 fps, 100 milliseconds

        void setup() {{
            Serial.begin({baudrate});
            Serial1.begin({baudrate});
            Serial2.begin({baudrate});
            for (int i = 0; i < numPins; i++) {{
                pinMode(pins[i], OUTPUT);
            }}
        }}

        void loop() {{
            unsigned long currentMillis = millis();
            
            if (currentMillis - previousMillis >= interval) {{
                previousMillis = currentMillis;

                Serial.println(message);
                Serial1.println(message);
                for (int i = 0; i < numPins; i++) {{
                    digitalWrite(pins[i], HIGH);
                }}

                delay(50);

                for (int i = 0; i < numPins; i++) {{
                    digitalWrite(pins[i], LOW);
                }}
            }}
        }}
        """
        with open("main_program_test.ino", "w") as f:
            f.write(arduino_code)

        subprocess.run(
            [
                "arduino-cli",
                "compile",
                "--fqbn",
                "arduino:avr:mega",
                "main_program_test.ino",
            ],
            check=True,
        )

    def get_encoded_message(self):
        selected_encoder = self.encoder_combo.currentText()
        message = self.write_message_edit.text()
        print(message, "message")
        try:
            encoding_methods = {
                "ASCII": "ascii",
                "UTF-8": "utf-8",
                "UTF-16": "utf-16",
                "ISO-8859-1": "iso-8859-1",
                "UTF-32": "utf-32",
            }
            # return message.encode(encoding_methods.get(selected_encoder, "utf-8"))
            return message.encode(selected_encoder)
        except UnicodeEncodeError as e:
            QMessageBox.critical(self, "Encoding Error", f"Encoding failed: {e}")
            return False
        except Exception as e:
            QMessageBox.critical(self, "Encoding Error", f"Encoding failed: {e}")
            return False

    def format_message(self, encoded_message):
        selected_format = self.format_combo.currentText()

        format_methods = {
            "STX/ETX": lambda msg: b"\x02" + msg + b"\x03",
            "CRLF": lambda msg: msg + b"\r\n",
            "LF": lambda msg: msg + b"\n",
            "CR": lambda msg: msg + b"\r",
        }
        return format_methods.get(selected_format, lambda msg: msg)(encoded_message)

    def on_prev(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setCurrentIndex(current_index - 1)

    def on_next(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setTabEnabled(current_index + 1, True)
        self.tab_widget.setCurrentIndex(current_index + 1)

    def start_reading_thread(self):
        # Start a thread to continuously read from the serial port
        def read_from_port():
            self.serial_connection.read_all()
            while self.serial_connection and self.serial_connection.is_open:
                if self.serial_connection and self.serial_connection.in_waiting > 0:
                    line = self.serial_connection.readline().decode("utf-8").strip()
                    self.text_edit.append(line)

        thread = threading.Thread(target=read_from_port, daemon=True)
        thread.start()


class UploadDialog(QDialog):
    from PyQt5.QtCore import pyqtSignal

    upload_port = pyqtSignal(str)
    uploaded_port = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload to Arduino")
        self.initUI()
        self.load_ports()
        self.upload_port.connect(self.upload_info)
        self.uploaded_port.connect(self.uploaded_info)

    def initUI(self):
        layout = QVBoxLayout()
        description = QLabel(
            "<b>업로드 도움말</b><br>"
            "<b>업로드 실패 시 사용 포트에 대해서 1분 내외의 사용 제한이 걸립니다. </b><br>"
            "<b>1번 사용 권장</b>"
            "<p><b>방법 1:</b> 업로드용 포트를 빼기 전후를 비교해 특정 포트로 업로드합니다.</p>"
            "<p><b>방법 2:</b> 업로드용 포트를 알지 못할 때 모든 포트에 대해서 전부 시도합니다.</p>"
        )
        layout.addWidget(description)
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo)

        self.refresh_button = QPushButton("포트 새로 고침")
        self.refresh_button.clicked.connect(self.load_ports)
        layout.addWidget(self.refresh_button)

        # Upload buttons
        button_layout = QHBoxLayout()

        self.upload_selected_button = QPushButton("선택 포트에 업로드")
        self.upload_selected_button.clicked.connect(self.upload_to_selected_port)
        button_layout.addWidget(self.upload_selected_button)

        self.upload_all_button = QPushButton("모든 포트에 업로드")
        self.upload_all_button.clicked.connect(self.upload_to_all_ports)
        button_layout.addWidget(self.upload_all_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def load_ports(self):
        self.port_combo.clear()
        ports = list(serial.tools.list_ports.comports())
        self.port_combo.addItems([port.device for port in ports])
        if not ports:
            QMessageBox.warning(
                self,
                "Warning",
                "No serial ports found. Please check your connections and refresh.",
            )

    def upload_to_all_ports(self):
        ports = [self.port_combo.itemText(i) for i in range(self.port_combo.count())]
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        message = self.parent().message_edit.text()
        baudrate = self.parent().baudrate_combo.currentText()
        if not message:
            QMessageBox.warning(self, "Warning", "Test용 메시지를 써주세요")
            return
        print(message, baudrate, "hi")
        self.parent().create_arduino_sketch(message, baudrate)
        # baudrate = self.parent
        from threading import Thread

        for port in ports:
            Thread(
                target=self.upload_sketch, args=(port, root_config), daemon=True
            ).start()

    def upload_to_selected_port(self):
        port = self.port_combo.currentText()
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        message = self.parent().message_edit.text()
        baudrate = self.parent().baudrate_combo.currentText()

        self.parent().create_arduino_sketch(message, baudrate)
        if port:
            self.upload_sketch(port, root_config)
        else:
            QMessageBox.warning(self, "Warning", "Please select a port to upload.")
            return

    def upload_sketch(self, port, root_config: RootConfig):
        self.upload_port.emit(port)
        config = root_config.config
        upload_process = subprocess.Popen(
            [
                "arduino-cli",
                "upload",
                "-p",
                port,
                "--fqbn",
                "arduino:avr:mega",
                "main_program_test.ino",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = upload_process.communicate()

        if upload_process.returncode == 0:
            config.arduino_config.port = port
            config.arduino_config.baudrate = int(
                self.parent().baudrate_combo.currentText()
            )
            config.arduino_config.test_message = self.parent().message_edit.text()

            save_config(root_config)
            self.parent().tab_widget.load_previous_settings()
            self.uploaded_port.emit(True, f"{port} 업로드 성공 및 저장 완료!")
        else:
            self.uploaded_port.emit(False, f"{port} 업로드 실패: {stderr}")

    def upload_info(self, port):
        QMessageBox.information(self, "업로드 진행 시작..", port)

    def uploaded_info(self, is_succeed, port):
        if is_succeed:
            QMessageBox.information(self, "업로드 성공", port)
        else:
            QMessageBox.information(self, "업로드 실패", port)

    def closeEvent(self, event):
        self.reject()  # Ensure the dialog is properly closed


class ArduinoUploadTab(QWidget):
    def __init__(self, parent=None, tab_widget=None):
        super(ArduinoUploadTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        self.label = QLabel("3. 프로덕션 아두이노 코드 업로드")
        # TODO local_server에서 app_start이외에 upload_arduino
        layout.addWidget(self.label)

        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.on_prev)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.on_next)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.prev_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.next_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def on_prev(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setCurrentIndex(current_index - 1)

    def on_next(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setTabEnabled(current_index + 1, True)
        self.tab_widget.setCurrentIndex(current_index + 1)


class ConveyorMessageTab(QWidget):
    def __init__(self, parent=None, tab_widget=None):
        super(ConveyorMessageTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        self.label = QLabel("선별기 메시지 전송")
        layout.addWidget(self.label)

        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.on_prev)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.prev_button)
        button_layout.addStretch(1)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def on_prev(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setCurrentIndex(current_index - 1)


class SerialConfigTab(QWidget):
    def __init__(self, parent=None, tab_widget=None):
        super(SerialConfigTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()
        self.label = QLabel("프로덕션 시리얼 세팅")


class SpecificationUploadTab(QWidget):
    def __init__(self, parent=None, tab_widget=None):
        super(SpecificationUploadTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.initUI()

    def initUI(self):
        self.layout = QVBoxLayout()
        self.label = QLabel("명세서 업로드")
        self.layout.addWidget(self.label)

        self.upload_button = QPushButton("Upload pyproject.toml")
        self.upload_button.clicked.connect(self.upload_file)
        self.layout.addWidget(self.upload_button)

        # TODO 저장
        self.sender_combo = QComboBox()
        self.layout.addWidget(self.sender_combo)

        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.on_prev)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.on_next)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.prev_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.next_button)

        self.layout.addLayout(button_layout)

        self.setLayout(self.layout)

    def upload_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select pyproject.toml",
            "",
            "TOML Files (*.toml);;All Files (*)",
            options=options,
        )
        if not file_name:
            QMessageBox.warning(self, "Warning", "file을 선택해주세요")
            return
        QMessageBox.information(self, "설치", "필요한 모듈을 설치합니다.")
        self.process_toml_file(file_name)

    def is_package_importable(self, package_name):
        try:
            importlib.import_module(package_name)
            return True
        except ImportError:
            return False

    def process_toml_file(self, file_path):
        try:
            with open(file_path, "r") as toml_file:
                toml_data = toml.load(toml_file)
                print(
                    toml_data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                )
            self.install_dependencies(
                toml_data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to load or process TOML file: {e}"
            )
        else:
            self.update_senders_dropdown()
            QMessageBox.information(self, "완료", "프로그램 다운로드 완료")

    def update_senders_dropdown(self):
        try:
            sender_module = importlib.import_module("result_sender")
            all_senders = getattr(sender_module, "__all_senders__", [])
            self.sender_combo.addItems(all_senders)
        except ImportError:
            QMessageBox.warning(
                self,
                "Module Error",
                "result_sender module not found or does not have __all_senders__ attribute.",
            )

    def install_dependencies(self, dependencies):
        backup_pyproject = "pyproject.toml.bak"
        backup_lockfile = "poetry.lock.bak"

        try:
            # pyproject.toml과 poetry.lock 파일의 백업 생성
            shutil.copyfile("pyproject.toml", backup_pyproject)
            if os.path.exists("poetry.lock"):
                shutil.copyfile("poetry.lock", backup_lockfile)

            # dependencies에 있는 패키지를 모두 제거
            for package in list(dependencies.keys()):
                if package == "python":
                    continue
                subprocess.run(["poetry", "remove", package], check=True)

            # dependencies에 있는 패키지를 모두 추가
            for package, version in dependencies.items():
                if package == "python":
                    continue
                self.install_dependency(package, version)

        except Exception as e:
            # 작업 중 실패한 경우, 백업 파일을 복원하고 poetry update 실행
            print(f"작업 실패: {e}")
            QMessageBox.critical(
                self, "Error", f"Failed during dependency installation: {e}"
            )

            # 백업 파일 복원
            shutil.copyfile(backup_pyproject, "pyproject.toml")
            if os.path.exists(backup_lockfile):
                shutil.copyfile(backup_lockfile, "poetry.lock")

            # poetry update 실행
            try:
                subprocess.run(["poetry", "update"], check=True)
            except subprocess.CalledProcessError as update_error:
                print(f"poetry update 실패: {update_error}")
                QMessageBox.critical(
                    self, "Error", f"Failed to update dependencies: {update_error}"
                )

        else:
            print("Dependencies installed successfully.")
            QMessageBox.information(self, "완료", "모든 패키지 설치 완료.")
        finally:
            # 백업 파일 삭제
            if os.path.exists(backup_pyproject):
                os.remove(backup_pyproject)
            if os.path.exists(backup_lockfile):
                os.remove(backup_lockfile)

    def install_dependency(self, package, version):
        try:
            if isinstance(version, dict):
                # Git 저장소에서 패키지 설치
                git_url = version.get("git")
                rev = version.get("rev", "")
                branch = version.get("branch", "")
                command = ["poetry", "add"]
                repo_command = f"{package}@git+{git_url}"
                if rev:
                    repo_command += f"@{rev}"
                elif branch:
                    repo_command += f"@{branch}"
                command.append(repo_command)
            else:
                # 일반적인 패키지 설치
                command = ["poetry", "add", f"{package}={version}"]

            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stdout, stderr = process.communicate()

            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode, command, output=stdout, stderr=stderr
                )

            print(f"패키지 {package} 설치 완료: {stdout}")
        except subprocess.CalledProcessError as e:
            print(f"패키지 {package} 설치 실패: {e.stderr}, {stdout}")
            QMessageBox.critical(
                self, "Installation Error", f"패키지 {package} 설치 실패: {e.stderr}"
            )

    def on_prev(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setCurrentIndex(current_index - 1)

    def on_next(self):
        missing_packages = self.tab_widget.check_packages()
        if missing_packages:
            QMessageBox.critical(
                self, "설치 필요", f"패키지 [{', '.join(missing_packages)}]가 없습니다."
            )

        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setTabEnabled(current_index + 1, True)
        self.tab_widget.setCurrentIndex(current_index + 1)


def merge_toml_files(existing_toml_path, new_toml_path):
    with open(existing_toml_path, "r") as f:
        existing_toml = toml.load(f)

    with open(new_toml_path, "r") as f:
        new_toml = toml.load(f)

    # Merge the two toml dictionaries
    merged_toml = {**existing_toml, **new_toml}

    with open(existing_toml_path, "w") as f:
        toml.dump(merged_toml, f)

    return merged_toml


class SignalSettings(QTabWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.setup_logging()
        self.setup_shortcuts()
        self.load_previous_settings()
        self.update_tab_enablement()
        self.need_packages = ["result_sender", "local_server"]

    def initUI(self):
        self.line_count_tab = LineCountTab(self, tab_widget=self)
        self.serial_test_tab = SerialTestTab(self, tab_widget=self)
        self.arduino_upload_tab = ArduinoUploadTab(self, tab_widget=self)
        self.conveyor_message_tab = ConveyorMessageTab(self, tab_widget=self)
        self.specification_upload_tab = SpecificationUploadTab(self, tab_widget=self)

        self.addTab(self.line_count_tab, "라인 개수 입력")
        self.addTab(self.serial_test_tab, "시리얼 테스트")
        self.addTab(self.specification_upload_tab, "명세서 업로드")
        self.addTab(self.arduino_upload_tab, "프로덕션 아두이노 코드 업로드")
        self.addTab(self.conveyor_message_tab, "선별기 메시지 전송")

        self.setTabEnabled(1, False)
        self.setTabEnabled(2, False)
        self.setTabEnabled(3, False)
        self.setTabEnabled(4, False)

        # Add file upload button

    def load_previous_settings(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        self.line_count_tab.line_edit.setText(str(config.program_config.line_count))
        self.setTabEnabled(1, True)
        self.serial_test_tab.message_edit.setText(config.arduino_config.test_message)
        self.serial_test_tab.baudrate_combo.setCurrentText(
            str(config.arduino_config.baudrate)
        )
        self.serial_test_tab.write_message_edit.setText(
            config.serial_config.test_message_to_sorter
        )
        self.serial_test_tab.write_baudrate_combo.setCurrentText(
            str(config.serial_config.baudrate)
        )

        self.serial_test_tab.encoder_combo.setCurrentText(
            config.serial_config.test_message_encode_type.value
        )
        self.serial_test_tab.format_combo.setCurrentText(
            config.serial_config.test_message_format_type.value
        )

        self.setTabEnabled(2, True)

    def update_tab_enablement(self):
        # TODO 순차적으로 돌면서 막히는 곳을 막음
        # line_count가 0이면 막기부터 시작
        if self.line_count_tab.line_edit.text():
            self.setTabEnabled(1, True)
        if (
            self.serial_test_tab.message_edit.text()
            and self.serial_test_tab.baudrate_combo.currentText()
        ):
            self.setTabEnabled(2, True)
        # Additional conditions for other tabs can be added here

    def setup_logging(self):
        logging.basicConfig(
            filename="settings.log",
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
        )
        logging.info("Program started.")

    def setup_shortcuts(self):
        quit_action = QAction(QIcon("exit.png"), "Exit", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.handle_quit)

        self.addAction(quit_action)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)

    def handle_quit(self):
        self.close()

    def upload_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload pyproject.toml",
            "",
            "TOML Files (*.toml);;All Files (*)",
            options=options,
        )
        if file_path:
            existing_pyproject_path = "path/to/existing/pyproject.toml"  # Set your existing pyproject.toml path
            try:
                merge_toml_files(existing_pyproject_path, file_path)
                QMessageBox.information(
                    self, "Success", "pyproject.toml 파일이 성공적으로 병합되었습니다."
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"파일 병합 중 오류가 발생했습니다: {e}"
                )

    def check_packages(self):
        missing_packages = []

        for package in self.need_packages:
            if not self.is_package_importable(package):
                missing_packages.append(package)
        return missing_packages


if __name__ == "__main__":
    backup_config()
    app = QApplication(sys.argv)
    ex = SignalSettings()
    ex.show()
    sys.exit(app.exec_())
