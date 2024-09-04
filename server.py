import json
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget
from PyQt5.QtCore import QObject, QThread, pyqtSignal
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
import traceback
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
import traceback
import logging
from queue import Queue


app = FastAPI()
data_queue = Queue()  # Shared queue for communication

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# FastAPI 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fastapi")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # 요청 로깅
    logger.info(f"Request: {request.method} {request.url}")
    try:
        # 요청 처리
        response = await call_next(request)
        logger.info(f"Response: {response.status_code} {response.headers.get('content-type')}")
        return response
    except Exception as exc:
        # 예외 로그 기록
        logger.error(f"Exception occurred: {exc}, Traceback: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={"message": "An internal error occurred."}
        )

@app.get("/")
def read_root():
    logger.info("Root endpoint hit")
    return {"Hello": "World"}
from server_config_model import RootConfig, ServerConfig, load_server_root_config

@app.get("/setting")
def read_root(request: Request):
    root_config: RootConfig = load_server_root_config()
    config: ServerConfig = root_config.config
    client_ip = request.client.host
    for line in config.program_config.lines:
        if client_ip == line.ip:
            return {"line": line.line_idx, "number_of_cut": config.serial_config.signal_count_per_pulse, "subharmonic_signal": config.serial_config.signal_count_per_pulse}
    return Response(status_code=status.HTTP_204_NO_CONTENT)
connected_line_set = set()
connected_lines = {}

async def broadcast_to_lines(data: dict):
    message = json.dumps(data)  # Convert the dictionary to a JSON string
    for client in connected_lines.values():
        await client.send_text(message)

async def broadcast_message(message: str):
    for client in connected_lines:
        await client.send_text(message)

@app.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    client_ip = websocket.client.host
    
    connected_line_set.add(websocket)
    
    logger.info(f"Client {client_ip} IP.  Total lines: {len(connected_line_set)}")

    # Prepare the data to be broadcasted
    data = {
        "line_idx": None,
        "number_of_cut": None,
    }
    root_config: RootConfig = load_server_root_config()
    config: ServerConfig = root_config.config
    saved_lines = config.program_config.lines
    for saved_client in saved_lines:
        if str(client_ip) == saved_client.ip:
            data = {
                "line_idx": saved_client.line_idx,
                "number_of_cut": config.serial_config.signal_count_per_pulse,
                "subharmonic_signal": config.serial_config.signal_count_per_pulse
            }
    await websocket.send_text(json.dumps(data))
    
    try:
        while True:
            received_data = await websocket.receive_text()
            data_queue.put({"line_idx": 0, "count_flag": 0})
            logger.info(f"Received data from {client_ip}: {received_data}")
            await websocket.send_text(f"Message received: {received_data}")
    except WebSocketDisconnect:
        # Remove the line on disconnection
        # del connected_lines[line_ip]
        connected_line_set.remove(websocket)
        logger.info(f"Client {client_ip} disconnected. Total lines: {len(connected_line_set)}")

class QTextEditHandler(logging.Handler):
    def __init__(self, log_signal):
        super().__init__()
        self.log_signal = log_signal

    def emit(self, record):
        log_entry = self.format(record)
        self.log_signal.emit(log_entry)

class FastAPIServerThread(QThread):
    # 로그 업데이트 시그널
    log_signal = pyqtSignal(str)

    def run(self):
        # FastAPI 서버 실행
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        
        # 로그 핸들러 설정
        text_edit_handler = QTextEditHandler(self.log_signal)
        # line_count_handler = QTextEditHandler(self.)
        text_edit_handler.setFormatter(logging.Formatter('%(asctime)s - %(threadName)s - %(message)s'))
        logger.addHandler(text_edit_handler)
        # FastAPI 서버 실행
        server.run()

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
        self.server_thread = FastAPIServerThread()
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
