import asyncio
import importlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from enum import Enum

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
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    qApp,
)
from server_config_model import (
    EncodingEnum,
    FormatEnum,
    Line,
    RootConfig,
    ServerConfig,
    backup_config,
    load_server_root_config,
    save_config,
)

from result_sender_thread import ResultSenderThread
from server import FastAPIServerThread, broadcast_message


class NeedPackageEnum(str, Enum):
    ResultSender = "result_sender"
    LocalServer = "local_server"


class TabIndexEnum(Enum):
    LINE_COUNT = 0
    SERIAL_TEST = 1
    SPECIFICATION_UPLOAD = 2
    ARDUINO_UPLOAD = 3
    CONVEYOR_MESSAGE = 4


class LineCountTab(QWidget):
    def __init__(self, parent=None, tab_widget=None, main_widget=None):
        super(LineCountTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.main_widget = main_widget
        self.initUI()

    def initUI(self):

        if self.layout() is not None:
            # 기존 레이아웃을 새로운 빈 QWidget에 설정하여 제거
            QWidget().setLayout(self.layout())

        # 새로운 레이아웃 설정
        layout = QVBoxLayout(self)

        line_layout = QHBoxLayout()
        self.label = QLabel("1. 라인 개수 입력")
        self.line_edit = QLineEdit()
        line_layout.addWidget(self.label)
        line_layout.addWidget(self.line_edit)
        self.line_edit.setValidator(QIntValidator())  # Allow only integers

        # ipconfig 결과를 보여주는 섹션
        ipconfig_layout = QVBoxLayout()
        ipconfig_label = QLabel("2. 현재 프로그램의 ipconfig 결과:")

        self.ipconfig_text = QTextEdit()
        self.ipconfig_text.setReadOnly(True)

        # ipconfig 명령 실행 결과 가져오기
        ipconfig_result = self.get_ipconfig_result()
        self.ipconfig_text.setPlainText(ipconfig_result)

        ipconfig_layout.addWidget(ipconfig_label)
        ipconfig_layout.addWidget(self.ipconfig_text)

        self.next_button = QPushButton("Save and Next")
        self.next_button.clicked.connect(self.on_next)
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.next_button)

        layout.addLayout(line_layout)
        layout.addLayout(ipconfig_layout)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        self.line_edit.setFocus()

    def get_ipconfig_result(self):
        try:
            # Windows에서 ipconfig 명령 실행 (Linux/Mac에서는 ifconfig 사용)
            result = subprocess.run(["ipconfig"], capture_output=True, text=True)
            return result.stdout
        except Exception as e:
            return f"Error: {e}"

    def on_next(self):
        line_count = self.line_edit.text()
        if not line_count or not int(line_count):
            QMessageBox.warning(
                self,
                "No line count",
                "라인 개수를 입력해주세요",
            )
            return

        # self.save_line_count(int(line_count))
        before_root_config: RootConfig = load_server_root_config()
        before_config: ServerConfig = before_root_config.config
        before_line_count = before_config.program_config.line_count
        is_read_configured = before_config.serial_config.is_read_configured
        is_send_configured = before_config.serial_config.is_send_configured
        production_module = before_config.serial_config.production_result_sender_module
        print(
            [
                is_read_configured,
                is_send_configured,
                int(before_line_count) != int(line_count),
            ]
        )
        if not any(
            [
                is_read_configured,
                is_send_configured,
                int(before_line_count) != int(line_count),
            ]
        ):  # 기존 설정이 아무 것도 없음
            self.save_line_count(int(line_count))
            current_index = self.tab_widget.currentIndex()
            self.tab_widget.setTabEnabled(current_index + 1, True)
            self.tab_widget.setCurrentIndex(current_index + 1)
            return
        # 라인 변경 시에 설정 값의 삭제를 확인합니다.
        reply = QMessageBox.question(
            self,
            "저장 확인",
            "라인 개수 변경 시에, 프로덕션 아두이노 설정을 다시 해야합니다. 진행하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        before_config.program_config.line_count = int(line_count)
        is_saved = self.main_widget.save_root_config(before_root_config)
        if not is_saved:
            return
        if not production_module:
            current_index = self.tab_widget.currentIndex()
            self.tab_widget.setCurrentIndex(current_index + 1)
            return

        try:
            result_sender_module = self.main_widget.get_result_sender_module(
                production_module
            )
            result_sender = getattr(result_sender_module, "ResultSender", None)
            if result_sender:
                result_sender.create_default_config()
            else:
                QMessageBox.critical(
                    self,
                    "오류",
                    "모듈을 불러오는 데 실패했습니다. 재실행 이후에도 같은 문제 발생 시 관리자 문의",
                )
                return
            QMessageBox.information(
                self, "완료", "설정이 성공적으로 변경되었습니다. 프로그램 재실행합니다."
            )
            self.main_widget.arduino_upload_tab.initUI()
        except ImportError as e:
            QMessageBox.critical(self, "오류 관리자 문의 필요", f"모듈 저장 실패: {e}")

    def save_line_count(self, line_count):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        if config is not None:
            config.program_config.line_count = line_count
            self.main_widget.save_root_config(root_config)


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
    def __init__(self, parent=None, tab_widget=None, main_widget=None):
        super(SerialTestTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.main_widget = main_widget
        self.serial_connection = None
        self.write_serial_connection = None
        self.initUI()
        self.process_running = False

    def initUI(self):
        layout = QVBoxLayout()

        if self.layout() is not None:
            # 기존 레이아웃을 새로운 빈 QWidget에 설정하여 제거
            QWidget().setLayout(self.layout())

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
            self.main_widget.update_log(f"Connected to {port} at {baudrate} baud.")
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
            self.main_widget.update_log(f"Connected to {port} at {baudrate} baud.")
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
            self.main_widget.update_log("Disconnected.")

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
            is_saved = self.main_widget.save_root_config(root_config=root_config)
            if not is_saved:
                return
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

        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config

        if not config.arduino_config.is_upload_port_assigned:
            QMessageBox.warning(
                self, "업로드 포트 확인", "읽기 테스트 아두이노 업로드를 진행해주세요."
            )
            return
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
                    self.main_widget.update_log(line)

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

        if self.layout() is not None:
            # 기존 레이아웃을 새로운 빈 QWidget에 설정하여 제거
            QWidget().setLayout(self.layout())

        # 새로운 레이아웃 설정
        layout = QVBoxLayout(self)
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
            config.arduino_config.is_upload_port_assigned = True
            config.serial_config.is_production_sketch_uploaded = False
            config.serial_config.is_read_configured = False
            config.serial_config.is_send_configured = False
            is_saved = self.parent().main_widget.save_root_config(root_config)
            self.uploaded_port.emit(True, f"{port} 업로드 성공 및 저장 완료!")
        else:
            self.uploaded_port.emit(False, f"{port} 업로드 실패: {stderr}")

    def upload_info(self, port):
        QMessageBox.information(self, "업로드 진행 시작..", port)

    def uploaded_info(self, is_succeed, port):
        if is_succeed:
            QMessageBox.information(self, "업로드 성공", port)
            self.accept()
        else:
            QMessageBox.information(self, "업로드 실패", port)

    def closeEvent(self, event):
        self.reject()  # Ensure the dialog is properly closed


# TODO 현재 config model 틀과 시리얼 틀 맞는 것만 display??  idea

# TODO 현재 모듈이 있으면 저장되어 있는 것 드롭다운 display, 선택할 수 있게


class ArduinoUploadTab(QWidget):
    def __init__(self, parent=None, tab_widget=None, main_widget=None):
        super(ArduinoUploadTab, self).__init__(parent)
        self.serial_result = None
        self.tab_widget = tab_widget
        self.main_widget = main_widget
        self.initUI()

    def initUI(self):
        self.root_config: RootConfig = load_server_root_config()
        self.config: ServerConfig = self.root_config.config
        # 기존 레이아웃 제거 (있을 경우)
        if self.layout() is not None:
            # 기존 레이아웃을 새로운 빈 QWidget에 설정하여 제거
            QWidget().setLayout(self.layout())

        # 새로운 레이아웃 설정
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Create scrollable area for input fields
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        input_group = QGroupBox("Inputs")
        input_group.setStyleSheet(
            "QGroupBox { background-color: lightgreen; }"
        )  # 배경색 설정
        input_layout = QFormLayout()

        self.input_fields = []

        available_ports = [port.device for port in serial.tools.list_ports.comports()]
        available_baudrates = [9600, 19200, 38400, 57600, 115200]
        available_input_pins = range(2, 10)

        signal_count_label = QLabel("신호당 총 신호 수:")
        self.signal_count_per_pulse = QSpinBox()
        self.signal_count_per_pulse.setRange(1, 5)
        self.signal_count_per_pulse.setValue(
            self.config.serial_config.signal_count_per_pulse
        )  # config에서 가져온 기본값 설정

        form_layout.addRow(signal_count_label, self.signal_count_per_pulse)
        layout.addLayout(form_layout)

        for idx, input_item in enumerate(self.config.serial_config.inputs):
            # Add index label
            input_layout.addRow(QLabel(f"Input {idx}"))
            input_port = QComboBox()
            input_port.addItems(available_ports)
            input_port.setCurrentText(input_item.port)

            input_baudrate = QComboBox()
            input_baudrate.addItems(map(str, available_baudrates))
            input_baudrate.setCurrentText(str(input_item.baudrate))

            input_pin = QComboBox()
            input_pin.addItems(map(str, available_input_pins))
            input_pin.setCurrentText(str(input_item.pin))

            # Camera delay - 정수 입력란
            camera_delay = QSpinBox()
            camera_delay.setRange(0, 3000)
            camera_delay.setValue(input_item.camera_delay)

            input_field_dict = {
                "port": input_port,
                "baudrate": input_baudrate,
                "pin": input_pin,
                "camera_delay": camera_delay,
            }

            self.input_fields.append(input_field_dict)

            input_layout.addRow(QLabel("Port:"), input_port)
            input_layout.addRow(QLabel("Baudrate:"), input_baudrate)
            input_layout.addRow(QLabel("Pin:"), input_pin)
            input_layout.addRow(QLabel("Camera Delay (ms):"), camera_delay)

            # Add a separator line
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            input_layout.addRow(line)

        input_group.setLayout(input_layout)
        scroll_layout.addWidget(input_group)

        # Create output section
        output_group = QGroupBox("Outputs")
        output_group.setStyleSheet(
            "QGroupBox { background-color: #ffb0c1; }"
        )  # 배경색 설정
        output_layout = QFormLayout()
        self.output_fields = []

        available_output_pins = range(30, 38)

        for idx, output_item in enumerate(self.config.serial_config.outputs):
            # Add index label
            output_layout.addRow(QLabel(f"Output {idx}"))

            output_port = QComboBox()
            output_port.addItems(available_ports)
            output_port.setCurrentText(output_item.port)

            output_baudrate = QComboBox()
            output_baudrate.addItems(map(str, available_baudrates))
            output_baudrate.setCurrentText(str(output_item.baudrate))

            output_offset = QSpinBox()
            output_offset.setRange(0, 1000)
            output_offset.setValue(output_item.offset)

            output_pin = QComboBox()
            output_pin.addItems(map(str, available_output_pins))
            output_pin.setCurrentText(str(output_item.pin))

            output_field_dict = {
                "port": output_port,
                "baudrate": output_baudrate,
                "pin": output_pin,
                "offset": output_offset,
            }

            self.output_fields.append(output_field_dict)

            output_layout.addRow(QLabel("Port:"), output_port)
            output_layout.addRow(QLabel("Baudrate:"), output_baudrate)
            output_layout.addRow(QLabel("Offset:"), output_offset)
            output_layout.addRow(QLabel("Pin:"), output_pin)

            # Add a separator line
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            output_layout.addRow(line)

        output_group.setLayout(output_layout)
        scroll_layout.addWidget(output_group)

        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        self.setWindowTitle("Serial Configuration")
        self.setGeometry(300, 300, 400, 300)
        button_layout = QHBoxLayout()

        validate_button = QPushButton("유효성 검사, 저장, 업로드")
        validate_button.clicked.connect(self.validate_inputs)

        button_layout.addWidget(validate_button)

        layout.addLayout(button_layout)

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

    def validate_inputs(self):
        before_root_config: RootConfig = load_server_root_config()
        self.save_config()
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        result_sender_module = config.serial_config.production_result_sender_module
        if not config.serial_config.production_result_sender_module:
            QMessageBox.critical(
                self, "모듈 에러", "현재 설정된 모듈이 없습니다. 관리자 문의."
            )
            return

        result_sender_module = self.main_widget.get_result_sender_module(
            result_sender_module
        )
        result_sender = getattr(result_sender_module, "ResultSender", None)
        try:
            result_sender.check_valid_config()
        except Exception as e:
            QMessageBox.critical(self, "유효성 검사 실패, ", f"{e}")
            self.main_widget.save_root_config(before_root_config)
            self.initUI()
            return

        reply = QMessageBox.question(
            self,
            "완료",
            "유효성 및 저장 완료했습니다. 업로드를 진행합니다.",
            # "변경 이후 프로그램 재실행됩니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        self.main_widget.update_log("업로드 시작.\n10초 내외의 시간이 걸립니다.")
        if reply == QMessageBox.No:
            return
        try:
            arduino_sketch = result_sender.get_arduino_sketch()
        except Exception as e:
            QMessageBox.critical(self, "유효성 검사 실패, ", f"{e}")
            self.main_widget.save_root_config(before_root_config)
            self.initUI()
            return

        with open("main_program_test.ino", "w", encoding="utf-8") as f:
            f.write(arduino_sketch)

        check_process = subprocess.Popen(
            [
                "arduino-cli",
                "compile",
                "--fqbn",
                "arduino:avr:mega",
                "main_program_test.ino",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",  # 인코딩을 명시적으로 설정
        )
        chk_stdout, chk_stderr = check_process.communicate()
        self.main_widget.update_log(chk_stdout)
        if check_process.returncode != 0:
            QMessageBox.critical(
                self,
                "실패",
                f"아두이노 코드 에러. 관리자에게 문의 필요합니다. {chk_stderr}",
            )
            return
        upload_process = subprocess.Popen(
            [
                "arduino-cli",
                "upload",
                "-p",
                config.arduino_config.port,
                "--fqbn",
                "arduino:avr:mega",
                "main_program_test.ino",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",  # 인코딩을 명시적으로 설정
        )
        stdout, stderr = upload_process.communicate()
        self.main_widget.update_log(stdout)
        if upload_process.returncode != 0:
            QMessageBox.critical(
                self, "실패", f"업로드 실패, 업로드 포트  확인 필요합니다. {stderr}"
            )
            return
        config.serial_config.is_production_sketch_uploaded = True
        self.main_widget.save_root_config(root_config)
        QMessageBox.information(self, "Success", "Uploaded arduino sketch!!")

    def save_config(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        serial_input_config_list = []
        serial_output_config_list = []
        for field_dict in self.input_fields:
            input_serial_config = {
                "port": field_dict["port"].currentText(),
                "baudrate": int(field_dict["baudrate"].currentText()),
                "pin": int(field_dict["pin"].currentText()),
                "camera_delay": field_dict["camera_delay"].value(),
            }
            serial_input_config_list.append(input_serial_config)

        for field_dict in self.output_fields:
            output_serial_config = {
                "port": field_dict["port"].currentText(),
                "baudrate": int(field_dict["baudrate"].currentText()),
                "pin": int(field_dict["pin"].currentText()),
                "offset": field_dict["offset"].value(),
            }
            serial_output_config_list.append(output_serial_config)

        config.serial_config.signal_count_per_pulse = (
            self.signal_count_per_pulse.value()
        )
        config.serial_config.inputs = serial_input_config_list
        config.serial_config.outputs = serial_output_config_list
        is_saved = self.main_widget.save_root_config(root_config=root_config)
        if not is_saved:
            return

    def on_prev(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setCurrentIndex(current_index - 1)

    def on_next(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        if not config.serial_config.is_production_sketch_uploaded:
            QMessageBox.warning(
                self, "유효성 검사", "유효성 검사와 아두이노 업로드 이후에 가능합니다."
            )
            return
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setTabEnabled(current_index + 1, True)
        self.tab_widget.setCurrentIndex(current_index + 1)


class TableHeaders(Enum):
    STATUS = "Status"
    IP = "IP"
    CLIENT_IDX = "Line Index"
    TEST_GRADE = "Test 등급"


class ConveyorMessageTab(QWidget):
    def __init__(
        self,
        parent=None,
        tab_widget=None,
        main_widget=None,
        loop=None,
        result_data_queue=None,
    ):
        super(ConveyorMessageTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.main_widget = main_widget
        self.loop = loop
        self.result_data_queue = result_data_queue
        self.result_sender_thread = None
        self.initUI()

    def initUI(self):
        root_config: RootConfig = load_server_root_config()
        self.config: ServerConfig = root_config.config

        if self.layout() is not None:
            # 기존 레이아웃을 새로운 빈 QWidget에 설정하여 제거
            QWidget().setLayout(self.layout())
        # 새로운 레이아웃 설정
        layout = QVBoxLayout(self)

        self.label = QLabel("선별기 메시지 전송")
        layout.addWidget(self.label)

        # Create the table
        self.table = QTableWidget()
        self.table.setRowCount(self.config.program_config.line_count)
        self.table.setColumnCount(4)  # Status, IP, Line Index, Test 등급

        self.table.setHorizontalHeaderLabels(
            ["Status", "IP", "Line Index", "Test 등급"]
        )
        from server import connected_line_set

        connected_ip_list = [line.client.host for line in connected_line_set]
        lines = sorted(self.config.program_config.lines, key=lambda c: c.ip)
        for idx, line in enumerate(lines):
            # Status Column (green/gray)
            status_item = QTableWidgetItem()
            status_item.setFlags(Qt.ItemIsEnabled)  # Make it read-only
            status_item.setBackground(
                Qt.green if line.ip in connected_ip_list else Qt.gray
            )
            self.table.setItem(idx, 0, status_item)

            # IP Column (ensuring valid IP format)
            ip_item = QTableWidgetItem(line.ip)
            self.table.setItem(idx, 1, ip_item)

            # Line Index Column (ensuring integer values only)
            line_idx_item = QTableWidgetItem(str(line.line_idx))
            self.table.setItem(idx, 2, line_idx_item)

            #
            test_grade_item = QTableWidgetItem(0)
            self.table.setItem(idx, 3, test_grade_item)

        # Save Button to store the IP and Line Index
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_config)
        layout.addWidget(save_button)

        # Refresh Button
        self.refresh_button = QPushButton("새로고침")
        self.refresh_button.clicked.connect(self.refresh_btn)
        layout.addWidget(self.refresh_button)

        self.sync_button = QPushButton("동기화")
        self.sync_button.clicked.connect(self.fruit_from_gpu)
        layout.addWidget(self.sync_button)

        self.sync_offset_button = QPushButton("선별기 offset 맞춤 작업 시작")
        self.sync_offset_button.clicked.connect(self.sync_offset_to_sorter)
        layout.addWidget(self.sync_offset_button)

        # Previous Button
        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.on_prev)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.prev_button)
        button_layout.addStretch(1)

        layout.addLayout(button_layout)
        layout.addWidget(self.table)

        # Listing connected IPs
        self.connected_ips_table = QTableWidget()
        self.connected_ips_table.setRowCount(len(connected_ip_list))
        self.connected_ips_table.setColumnCount(1)
        self.connected_ips_table.setHorizontalHeaderLabels(["Connected IPs"])

        for i, ip in enumerate(connected_ip_list):
            ip_item = QTableWidgetItem(ip)
            self.connected_ips_table.setItem(i, 0, ip_item)

        layout.addWidget(self.connected_ips_table)

        self.setLayout(layout)

    def sync_offset_to_sorter(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config

        result_sender_module = self.main_widget.get_result_sender_module(
            config.serial_config.production_result_sender_module
        )
        result_sender_class = getattr(result_sender_module, "ResultSender", None)
        # TODO result_sender는 스레드고 self.result_sender_thread로 지정한다.
        # result_sender스레드가 지정되어 있다면 강제 종료시킨다.
        if self.result_sender_thread and self.result_sender_thread.is_alive():
            self.result_sender_thread.stop()
            self.result_sender_thread.join()

        try:
            self.result_sender_thread = ResultSenderThread(
                result_data_queue=self.result_data_queue
            )
            self.result_sender_thread.log_signal.connect(self.main_widget.update_log)
            self.result_sender_thread.start()
        except Exception as e:
            if self.result_sender_thread and self.result_sender_thread.is_alive():
                self.result_sender_thread.stop()
                self.result_sender_thread.join()
            print(e)

    def fruit_from_gpu(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config

        from server_config_app import connected_line_set

        saved_lines = config.program_config.lines
        for ws in connected_line_set:
            for saved_line in saved_lines:
                if str(ws.client.host) == saved_line.ip:
                    data = {
                        "line_idx": saved_line.line_idx,
                        "number_of_cut": config.serial_config.signal_count_per_pulse,
                    }
                    asyncio.run_coroutine_threadsafe(
                        self.send_message_to_line(ws, data), self.loop
                    )

    async def send_message_to_line(self, ws, data: dict):
        data = json.dumps(data)
        await ws.send_text(data)

    def save_config(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        lines = []
        for row in range(self.table.rowCount()):
            ip_item = self.table.item(row, 1)
            line_idx_item = self.table.item(row, 2)

            if ip_item is None:
                QMessageBox.warning(
                    self, "Missing Data", f"Row {row + 1} has an empty IP cell."
                )
                return

            if line_idx_item is None:
                QMessageBox.warning(
                    self, "Missing Data", f"Row {row + 1} has an empty Line Index cell."
                )
                return
            try:
                # Validate line index is an integer
                line_idx = int(line_idx_item.text())
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Invalid Line Index",
                    f"Row {row + 1} has a non-integer line index.",
                )
                return
            lines.append(Line(ip=ip_item.text(), line_idx=line_idx))
            # Here you would save the IP and line_idx to your config or database
            print(f"Saving IP: {ip_item.text()}, Line Index: {line_idx}")
        config.program_config.lines = lines
        is_saved = self.main_widget.save_root_config(root_config)
        if not is_saved:
            return
        QMessageBox.information(self, "Success", "Configuration saved successfully.")
        self.initUI()

    def refresh_btn(self):
        self.initUI()

    async def send_message_to_lines(self, message):
        await broadcast_message(message)

    def update_status(self, ip, is_connected):
        # Find the row by IP and update the status
        for row in range(self.table.rowCount()):
            ip_item = self.table.item(row, 1)
            if ip_item.text() == ip:
                status_item = self.table.item(row, 0)
                if is_connected:
                    status_item.setBackground(Qt.green)  # Set to green if connected
                else:
                    status_item.setBackground(Qt.gray)  # Set to gray if disconnected
                break

    def on_prev(self):
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setCurrentIndex(current_index - 1)


class SpecificationUploadTab(QWidget):
    def __init__(self, parent=None, tab_widget=None, main_widget=None):
        super(SpecificationUploadTab, self).__init__(parent)
        self.tab_widget = tab_widget
        self.main_widget = main_widget
        self.initUI()

    def initUI(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config

        if self.layout() is not None:
            # 기존 레이아웃을 새로운 빈 QWidget에 설정하여 제거
            QWidget().setLayout(self.layout())
        # 새로운 레이아웃 설정
        self.main_layout = QVBoxLayout(self)

        self.upload_button = QPushButton("pyproject.toml 파일을 업로드해주세요.")
        self.upload_button.clicked.connect(self.upload_file)
        self.main_layout.addWidget(self.upload_button)

        self.sender_combo = QComboBox()
        self.main_layout.addWidget(self.sender_combo)
        serial_result_sender = config.serial_config.production_result_sender_module
        if self.main_widget.is_package_importable(
            f"{NeedPackageEnum.ResultSender.value}"
        ):
            sender_module = importlib.import_module(
                f"{NeedPackageEnum.ResultSender.value}"
            )
            all_senders = getattr(sender_module, "__all_senders__", [])
            self.sender_combo.clear()
            self.sender_combo.addItem("----")
            self.sender_combo.addItems(all_senders)
            self.sender_combo.setCurrentText(str(serial_result_sender))
        self.initializing = True
        self.sender_combo.currentTextChanged.connect(self.on_sender_combo_change)

        self.update_button = QPushButton("현재 프로그램 업데이트")
        self.update_button.clicked.connect(self.update_program)
        self.main_layout.addWidget(self.update_button)

        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.on_prev)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.on_next)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.prev_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.next_button)

        self.main_layout.addLayout(button_layout)

        self.setLayout(self.main_layout)

    def update_program(self):
        self.main_widget.update_log("인터넷 환경 및 용량에 따라 시간 차이가 생깁니다.")
        QMessageBox.information(
            self, "업데이트", "업데이트 이후 프로그램 재실행합니다."
        )

        try:
            # subprocess를 통해 업데이트 명령어 실행
            subprocess.run(["poetry", "update"], check=True)
        except subprocess.CalledProcessError as update_error:
            print(f"poetry update 실패: {update_error}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to update dependencies: {update_error}\n관리자 문의 필요",
            )
        else:
            QMessageBox.information(self, "완료", "업데이트 완료.")
            self.initUI()

    def on_sender_combo_change(self):
        if self.initializing:
            self.initializing = False
            return
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        current_value = self.sender_combo.currentText()
        production_serial = config.serial_config.production_result_sender_module
        if current_value == "----":
            QMessageBox.warning(self, "Warning", "초기 값 선택 불가")
            self.sender_combo.setCurrentText(str(production_serial))
            return

        if current_value == production_serial:
            self.sender_combo.setCurrentText(production_serial)
            return
        # 기존 값과 다른 경우 확인 창 표시
        reply = QMessageBox.question(
            self,
            "확인",
            f"현재 선택된 '{current_value}'로 변경 시에 해당 모듈에 맞는 기본 설정으로 바뀝니다. 변경하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            self.sender_combo.setCurrentText(production_serial)
            return
        try:
            result_sender_module = self.main_widget.get_result_sender_module(
                current_value
            )
            result_sender = getattr(result_sender_module, "ResultSender", None)
            if result_sender:
                result_sender.create_default_config()
            else:
                QMessageBox.critical(
                    self,
                    "오류",
                    "모듈을 불러오는 데 실패했습니다. 재실행 이후에도 같은 문제 발생 시 관리자 문의",
                )
                return
            # 설정을 실제로 업데이트
            root_config: RootConfig = load_server_root_config()
            config: ServerConfig = root_config.config
            config.serial_config.production_result_sender_module = current_value
            is_saved = self.main_widget.save_root_config(root_config)
            if not is_saved:
                return
            self.sender_combo.setCurrentText(current_value)
            QMessageBox.information(
                self, "완료", f"설정이 '{current_value}'로 성공적으로 변경되었습니다."
            )
            self.initUI()
        except ImportError as e:
            QMessageBox.critical(self, "오류", f"모듈 저장 실패: {e}")

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

    def process_toml_file(self, file_path):
        try:
            with open(file_path, "r") as toml_file:
                toml_data = toml.load(toml_file)
            self.install_dependencies(
                toml_data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to load or process TOML file: {e}"
            )
        else:
            QMessageBox.information(self, "완료", "프로그램 다운로드 프로세스 완료")

    def update_senders_dropdown(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        # TODO 기존 sender_combo 초기화
        self.sender_combo.clear()
        try:
            sender_module = importlib.import_module(
                f"{NeedPackageEnum.ResultSender.value}"
            )
            all_senders = getattr(sender_module, "__all_senders__", [])
            print(all_senders, "all_senders")
            self.sender_combo.addItems(all_senders)
        except ImportError:
            QMessageBox.warning(
                self,
                "Module Error",
                "result_sender module not found or does not have __all_senders__ attribute.",
            )
        else:
            self.sender_combo.setCurrentText(
                str(config.serial_config.production_result_sender_module)
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
                try:
                    subprocess.run(["poetry", "remove", package], check=True)
                except subprocess.CalledProcessError as remove_error:
                    print("Remove Error", remove_error)
                    continue

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
                    self,
                    "Error",
                    f"Failed to update dependencies: {update_error}" "관리자 문의 필요",
                )

        else:
            print("Dependencies installed successfully.")
            QMessageBox.information(self, "완료", "모든 패키지 설치 완료.")
            self.initUI()
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
        missing_packages = self.main_widget.check_packages()
        if missing_packages:
            QMessageBox.critical(
                self, "설치 필요", f"패키지 [{', '.join(missing_packages)}]가 없습니다."
            )
            return
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        if not config.serial_config.production_result_sender_module:
            QMessageBox.critical(
                self, "설정 값 필요", "프로덕션 시리얼 패키지를 지정해주세요."
            )
            return
        production_result_sender = self.main_widget.get_result_sender_module(
            config.serial_config.production_result_sender_module
        )

        if (
            not production_result_sender
        ):  # 실제 프로덕션 패키지를 실행했는지를 확인하는 부분
            QMessageBox.critical(
                self, "설정 값 필요", "프로덕션 시리얼 패키지를 지정해주세요."
            )
            return
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


from multiprocessing import Queue

from server import data_queue


# class SignalSettings(QTabWidget):
class SignalSettings(QWidget):
    def __init__(self, loop=None):
        super().__init__()
        self.loop = loop
        self.result_data_queue = data_queue
        self.initUI()
        self.setup_logging()
        self.setup_shortcuts()
        self.load_previous_settings()
        self.server_thread.start()
        self.need_packages = [package_enum.value for package_enum in NeedPackageEnum]

    def initUI(self):
        # 메인 레이아웃 설정
        main_layout = QVBoxLayout(self)

        # 탭 위젯을 위한 섹션
        self.previous_index = 0
        self.tab_widget = QTabWidget(self)
        self.line_count_tab = LineCountTab(
            self, tab_widget=self.tab_widget, main_widget=self
        )
        self.serial_test_tab = SerialTestTab(
            self, tab_widget=self.tab_widget, main_widget=self
        )
        self.specification_upload_tab = SpecificationUploadTab(
            self, tab_widget=self.tab_widget, main_widget=self
        )
        self.arduino_upload_tab = ArduinoUploadTab(
            self, tab_widget=self.tab_widget, main_widget=self
        )
        self.conveyor_message_tab = ConveyorMessageTab(
            self,
            tab_widget=self.tab_widget,
            main_widget=self,
            loop=self.loop,
            result_data_queue=self.result_data_queue,
        )

        self.tab_widget.addTab(self.line_count_tab, "라인 개수 입력")
        self.tab_widget.addTab(self.serial_test_tab, "시리얼 테스트")
        self.tab_widget.addTab(self.specification_upload_tab, "명세서 업로드")
        self.tab_widget.addTab(self.arduino_upload_tab, "프로덕션 아두이노 코드 업로드")
        self.tab_widget.addTab(self.conveyor_message_tab, "선별기 메시지 전송")

        # self.tab_widget.setTabEnabled(TabIndexEnum.SERIAL_TEST.value, False)
        # self.tab_widget.setTabEnabled(TabIndexEnum.SPECIFICATION_UPLOAD.value, False)
        # self.tab_widget.setTabEnabled(TabIndexEnum.ARDUINO_UPLOAD.value, False)
        # self.tab_widget.setTabEnabled(TabIndexEnum.CONVEYOR_MESSAGE.value, False)

        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        # 탭 위젯을 메인 레이아웃에 추가
        main_layout.addWidget(self.tab_widget)
        self.server_thread = FastAPIServerThread()
        # 로그 섹션 추가
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)  # 로그 창은 읽기 전용으로 설정
        self.server_thread.log_signal.connect(self.update_log)
        main_layout.addWidget(self.log_text_edit)

    def update_log(self, log_message):
        self.log_text_edit.append(log_message)

    def show_warning_and_set_tab(self, warning_message, tab_index):
        """경고 메시지를 표시하고 특정 탭으로 전환하는 함수"""
        self.tab_widget.setCurrentIndex(tab_index)
        QMessageBox.warning(self, "경고", warning_message)
        self.previous_index = tab_index

    def on_tab_changed(self, index):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config

        condition_list = [
            True,
            config.program_config.line_count,
            config.arduino_config.is_upload_port_assigned,
            config.serial_config.production_result_sender_module,
            config.serial_config.is_production_sketch_uploaded,
        ]

        # 탭이 뒤로 이동했을 경우에는 아무 작업도 하지 않음
        if index < self.previous_index or condition_list[index]:
            self.previous_index = index
            return

        # 현재 탭과 이동하려는 탭이 같은 경우 처리하지 않음
        if index == self.previous_index:
            return

        # 조건에 따른 경고 메시지 및 탭 전환 처리
        if not config.program_config.line_count:
            self.show_warning_and_set_tab(
                "라인 개수 지정을 해주세요", TabIndexEnum.LINE_COUNT.value
            )
            return

        if not config.arduino_config.is_upload_port_assigned:
            self.show_warning_and_set_tab(
                "테스트용 아두이노를 업로드하고 시리얼 선 테스트를 진행해 주세요",
                TabIndexEnum.SERIAL_TEST.value,
            )
            return

        if not config.serial_config.production_result_sender_module:
            self.show_warning_and_set_tab(
                "명세서 업로드 및 모듈을 선택해주세요",
                TabIndexEnum.SPECIFICATION_UPLOAD.value,
            )
            return

        if not config.serial_config.is_production_sketch_uploaded:
            self.show_warning_and_set_tab(
                "프로덕션 아두이노를 업로드해주세요", TabIndexEnum.ARDUINO_UPLOAD.value
            )
            return

        self.previous_index = index

    def load_previous_settings(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        serial_result_sender = config.serial_config.production_result_sender_module
        if self.is_package_importable(f"{NeedPackageEnum.ResultSender.value}"):
            sender_module = importlib.import_module(
                f"{NeedPackageEnum.ResultSender.value}"
            )
            all_senders = getattr(sender_module, "__all_senders__", [])
            self.specification_upload_tab.sender_combo.clear()
            self.specification_upload_tab.sender_combo.addItem("----")
            self.specification_upload_tab.sender_combo.addItems(all_senders)
        self.line_count_tab.line_edit.setText(str(config.program_config.line_count))

        if int(config.program_config.line_count):
            self.update_log("라인 수 지정 완료!")
            self.tab_widget.setTabEnabled(TabIndexEnum.SERIAL_TEST.value, True)
        else:
            self.update_log("**라인 수 지정 필요**")

        if config.arduino_config.is_upload_port_assigned:
            self.update_log("업로드 아두이노 포트 지정 완료!")
            self.tab_widget.setTabEnabled(TabIndexEnum.SPECIFICATION_UPLOAD.value, True)
        else:
            self.update_log("**업로드 아두이노 포트 지정 필요**")

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
        serial_result_sender_module = self.get_result_sender_module(
            f"{serial_result_sender}"
        )

        if serial_result_sender and serial_result_sender_module:
            self.specification_upload_tab.sender_combo.setCurrentText(
                serial_result_sender
            )
            self.tab_widget.setTabEnabled(TabIndexEnum.ARDUINO_UPLOAD.value, True)
            self.update_log("프로덕션 모듈 선택 완료!")
        else:
            self.update_log("**프로덕션 모듈 선택 필요**")

        if config.serial_config.is_production_sketch_uploaded:
            self.tab_widget.setTabEnabled(TabIndexEnum.CONVEYOR_MESSAGE.value, True)
            self.update_log("프로덕션 아두이노 코드 업로드 완료!")
        else:
            self.update_log("**프로덕션 아두이노 코드 업로드 필요**")

    def get_result_sender_module(self, result_sender: str):
        """ResultSender가 있는 모듈을 반환합니다"""
        target_module = (
            f"{NeedPackageEnum.ResultSender.value}.all_senders.{result_sender}"
        )
        if not self.is_package_importable(target_module):
            return None
        return importlib.import_module(target_module)

    def setup_logging(self):
        logging.basicConfig(
            filename="settings.log",
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
        )
        logging.info("Program started.")
        logging.info("Program started2.")

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

    def is_package_importable(self, package_name):
        try:
            importlib.import_module(package_name)
            return True
        except ImportError:
            return False

    def restart_program(self):
        """현재 실행 중인 프로그램을 재실행합니다."""
        try:
            python = sys.executable
            os.execl(python, python, *sys.argv)
        except Exception as e:
            print(f"Error restarting the program: {e}")
            sys.exit(1)  # 재실행에 실패한 경우 프로그램을 종료

    def save_root_config(self, root_config: RootConfig):
        try:
            save_config(root_config)
        except Exception as e:
            QMessageBox.critical(self, "저장 오류", f"저장 오류. 관리자 문의 필요 {e}")
            return False
        return True


def start_event_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


if __name__ == "__main__":
    new_loop = asyncio.new_event_loop()

    loop_thread = threading.Thread(
        target=start_event_loop, args=(new_loop,), daemon=True
    )
    loop_thread.start()
    # Start the event loop in a new thread
    backup_config()
    # TODO test_status를 True로 변경하고 종료 시에는 반드시 test_status를 false로 변경한다.
    app = QApplication(sys.argv)
    ex = SignalSettings(loop=new_loop)
    ex.show()
    sys.exit(app.exec_())


# 메시지 전송
# - result_sernder의 log를 찍어주는 것이 좋아보임
# - 시작했다는 알림 필요

# 메시지 전송 완료? -> 실제 프로그램 실행 하는 곳도 필요해보임
