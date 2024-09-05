from enum import Enum
import importlib
import sys
import time
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget
from PyQt5.QtCore import QThread, pyqtSignal
import logging
from queue import Queue
from server_config_model import RootConfig, ServerConfig, load_server_root_config


class QTextEditHandler(logging.Handler):
    def __init__(self, log_signal):
        super().__init__()
        self.log_signal = log_signal

    def emit(self, record):
        log_entry = self.format(record)
        self.log_signal.emit(log_entry)

class NeedPackageEnum(str, Enum):
    ResultSender = "result_sender"
    LocalServer = "local_server"
    
class ResultSenderThread(QThread):
    # 로그 업데이트 시그널
    log_signal = pyqtSignal(str)

    def __init__(self, result_data_queue: Queue) -> None:
        super().__init__()
        self.result_data_queue = result_data_queue
        self.logger = None
    def is_package_importable(self, package_name):
        try:
            importlib.import_module(package_name)
            return True
        except ImportError:
            return False

    def run(self):
        root_config: RootConfig = load_server_root_config()
        config: ServerConfig = root_config.config
        result_sender_name = config.serial_config.production_result_sender_module
        
        target_module = f"{NeedPackageEnum.ResultSender.value}.all_senders.{result_sender_name}"
        
        if not self.is_package_importable(target_module):
            raise ImportError("모듈 없는데요")
        result_sender_module = importlib.import_module(target_module)
        result_sender_class = getattr(result_sender_module, 'ResultSender')
        
        
        result_sender = result_sender_class(result_data_queue=self.result_data_queue)
        print(result_sender.name, 'result_sender.name')
        self.logger = logging.getLogger(f"{result_sender.name}")
        
        text_edit_handler = QTextEditHandler(self.log_signal)
        text_edit_handler.setFormatter(logging.Formatter('%(asctime)s - %(threadName)s - %(message)s'))
        self.logger.addHandler(text_edit_handler)
        result_sender.start()
            
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # FastAPI 서버 스레드 생성
        self.server_thread = ResultSenderThread(result_data_queue=Queue())
        self.server_thread.log_signal.connect(self.update_log)
        self.server_thread.start()

    def update_log(self, log_message):
        # QTextEdit에 로그 추가
        self.text_edit.append(log_message)

if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(qt_app.exec_())
