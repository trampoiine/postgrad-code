import socket
import struct
import sys
import time
import threading
import os
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication, QGridLayout, QGroupBox, QLabel, QMainWindow,
    QPushButton, QVBoxLayout, QWidget, QHBoxLayout, QMessageBox
)
from can_data_model import CANDataModel

class CANControllerGUI(QMainWindow):
    HOST = "127.0.0.1"       # 连实车改为 192.168.1.178
    PORT = 4001
    CAN_ID = 0x501
    SEND_INTERVAL_MS = 10    # 100 Hz
    PULSE_DURATION_MS = 100  # 跳变信号保持 100ms

    def __init__(self):
        super().__init__()
        self.data_model = CANDataModel()
        
        # 状态变量
        self.target_speed = 6
        self.brake = 0
        self.steer_angle = 0.0
        self.current_gear = 'P'
        self.hazard_on = False
        self.horn_on = False
        self.real_actual_speed = '--'
        
        # 跳变定时器标记
        self.jump_timer = QTimer(self)
        self.jump_timer.setSingleShot(True)
        self.jump_timer.timeout.connect(self.finish_jump)

        # 发送定时器
        self.send_timer = QTimer(self)
        self.send_timer.setTimerType(Qt.PreciseTimer)
        self.send_timer.timeout.connect(self.send_frame)
        
        # 接收线程控制
        self.is_running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.init_ui()
        self.setup_receiver()
        
        # 启动发送和跳变初始化
        self.trigger_jump(gear_val=4, mode_val=2) # 启动默认 P 档、自动驾驶模式
        self.send_timer.start(self.SEND_INTERVAL_MS)

    def init_ui(self):
        self.setWindowTitle("智能驾舱控制台 (PyQt5版)")
        self.resize(800, 600)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 状态提示 Toast
        self.toast_label = QLabel("", self)
        self.toast_label.setStyleSheet("background-color: rgba(0,0,0,200); color: white; padding: 10px; border-radius: 5px; font-size: 14px;")
        self.toast_label.setAlignment(Qt.AlignCenter)
        self.toast_label.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast_label.hide)

        # ====== 灯光与喇叭 ======
        group_light = QGroupBox("灯光与喇叭")
        light_layout = QHBoxLayout(group_light)
        self.btn_left = QPushButton("左转向灯")
        self.btn_right = QPushButton("右转向灯")
        self.btn_off = QPushButton("关闭转向灯")
        self.btn_hazard = QPushButton("双闪")
        self.btn_horn = QPushButton("喇叭")

        self.btn_left.clicked.connect(lambda: self.set_lamp(2))
        self.btn_right.clicked.connect(lambda: self.set_lamp(3))
        self.btn_off.clicked.connect(lambda: self.set_lamp(1))
        self.btn_hazard.clicked.connect(self.toggle_hazard)
        self.btn_horn.pressed.connect(self.horn_press)
        self.btn_horn.released.connect(self.horn_release)

        for btn in (self.btn_left, self.btn_right, self.btn_off, self.btn_hazard, self.btn_horn):
            light_layout.addWidget(btn)
        layout.addWidget(group_light)

        # ====== 方向盘 ======
        group_steer = QGroupBox("方向盘 (左正右负)")
        steer_layout = QHBoxLayout(group_steer)
        btn_steer_l = QPushButton("左转 +20°")
        btn_steer_r = QPushButton("右转 -20°")
        btn_steer_c = QPushButton("回正")
        self.lbl_steer = QLabel("当前: 0.0°")
        self.lbl_steer.setStyleSheet("font-weight: bold; color: #409eff;")

        btn_steer_l.clicked.connect(lambda: self.change_steer(20.0))
        btn_steer_r.clicked.connect(lambda: self.change_steer(-20.0))
        btn_steer_c.clicked.connect(lambda: self.change_steer(0, is_center=True))

        steer_layout.addWidget(btn_steer_l)
        steer_layout.addWidget(btn_steer_r)
        steer_layout.addWidget(btn_steer_c)
        steer_layout.addWidget(self.lbl_steer)
        layout.addWidget(group_steer)

        # ====== 车速与刹车 ======
        group_speed = QGroupBox("动力控制")
        speed_layout = QHBoxLayout(group_speed)
        
        self.btn_spd_down = QPushButton("-")
        self.btn_spd_up = QPushButton("+")
        self.lbl_target_spd = QLabel("目标车速: 6 km/h")
        self.lbl_target_spd.setStyleSheet("color: #409eff; font-weight: bold;")
        
        self.btn_spd_up.clicked.connect(lambda: self.change_speed(1))
        self.btn_spd_down.clicked.connect(lambda: self.change_speed(-1))

        btn_brk_down = QPushButton("-")
        btn_brk_up = QPushButton("+")
        self.lbl_brake = QLabel("制动踏板: 0 %")
        self.lbl_brake.setStyleSheet("color: #f56c6c; font-weight: bold;")
        
        btn_brk_up.clicked.connect(lambda: self.change_brake(5))
        btn_brk_down.clicked.connect(lambda: self.change_brake(-5))

        speed_layout.addWidget(self.btn_spd_down)
        speed_layout.addWidget(self.lbl_target_spd)
        speed_layout.addWidget(self.btn_spd_up)
        speed_layout.addSpacing(20)
        speed_layout.addWidget(btn_brk_down)
        speed_layout.addWidget(self.lbl_brake)
        speed_layout.addWidget(btn_brk_up)
        layout.addWidget(group_speed)

        # ====== 档位与复位 ======
        group_gear = QGroupBox("档位与系统")
        gear_layout = QHBoxLayout(group_gear)
        
        self.btn_p = QPushButton("P")
        self.btn_r = QPushButton("R")
        self.btn_n = QPushButton("N")
        self.btn_d = QPushButton("D")
        
        self.btn_p.clicked.connect(lambda: self.set_gear('P'))
        self.btn_r.clicked.connect(lambda: self.set_gear('R'))
        self.btn_n.clicked.connect(lambda: self.set_gear('N'))
        self.btn_d.clicked.connect(lambda: self.set_gear('D'))
        
        btn_reset = QPushButton("全部复位")
        btn_reset.setStyleSheet("color: red;")
        btn_reset.clicked.connect(self.reset_all)

        for b in (self.btn_p, self.btn_r, self.btn_n, self.btn_d):
            gear_layout.addWidget(b)
        gear_layout.addStretch()
        gear_layout.addWidget(btn_reset)
        layout.addWidget(group_gear)

        # ====== 底部数据面板 ======
        self.lbl_actual_speed = QLabel("实际车速: -- km/h")
        self.lbl_actual_speed.setStyleSheet("font-size: 24px; font-weight: bold; color: #f56c6c;")
        
        self.lbl_hex = QLabel("报文: 08 00 00 05 01 1F 00 00 00 00 00 00 00")
        self.lbl_hex.setStyleSheet("font-family: Consolas; color: gray;")
        
        layout.addWidget(self.lbl_actual_speed)
        layout.addWidget(self.lbl_hex)
        
        self.update_gear_ui()

    def show_toast(self, text):
        self.toast_label.setText(text)
        self.toast_label.adjustSize()
        self.toast_label.move((self.width() - self.toast_label.width()) // 2, (self.height() - self.toast_label.height()) // 2)
        self.toast_label.show()
        self.toast_label.raise_()
        self.toast_timer.start(2000)

    # ====== 发送与拼装逻辑 ======
    def trigger_jump(self, gear_val=None, lamp_val=None, mode_val=None):
        """处理跳变信号，保持100ms后自动清零"""
        if gear_val is not None:
            self.data_model.set_byte(5, (self.data_model.get_byte(5) & 0xF0) | (gear_val & 0x0F))
        if lamp_val is not None:
            self.data_model.set_byte(5, (self.data_model.get_byte(5) & 0xCF) | ((lamp_val & 0x03) << 4))
        if mode_val is not None:
            self.data_model.set_byte(7, mode_val)
        
        self.jump_timer.start(self.PULSE_DURATION_MS)

    def finish_jump(self):
        """100ms 到了，跳变信号清零"""
        self.data_model.set_byte(5, self.data_model.get_byte(5) & 0xF0 if self.current_gear not in ['R','N','D','P'] else self.data_model.get_byte(5) & 0xF0) # 低4位清零
        self.data_model.set_byte(5, self.data_model.get_byte(5) & 0xCF) # 转向灯位清零
        self.data_model.set_byte(7, 0x00)

    def send_frame(self):
        # Byte0 使能，Byte1 目标车速
        self.data_model.set_byte(0, 0x1F)
        self.data_model.set_byte(1, self.target_speed if self.current_gear in ['D', 'R'] else 0)
        
        # Byte2,3 方向盘
        raw_steer = int(self.steer_angle * 10)
        encoded_steer = raw_steer & 0xFFFF
        self.data_model.set_byte(2, (encoded_steer >> 8) & 0xFF)
        self.data_model.set_byte(3, encoded_steer & 0xFF)
        
        # Byte4 刹车
        self.data_model.set_byte(4, self.brake)
        
        # Byte5 灯光/双闪/喇叭 (档位和转向灯靠跳变另处理)
        b5 = self.data_model.get_byte(5)
        b5 = (b5 & 0x0F) | ((b5 & 0x30)) # 保留档位和转向灯低4位
        if self.hazard_on: b5 |= (1 << 6)
        else: b5 &= ~(1 << 6)
        if self.horn_on: b5 |= (1 << 7)
        else: b5 &= ~(1 << 7)
        self.data_model.set_byte(5, b5)

        # 组装 13 字节报文
        data = self.data_model.get_data()
        frame = struct.pack(">BI8B", 0x08, self.CAN_ID, *data)
        
        try:
            self.sock.sendto(frame, (self.HOST, self.PORT))
            self.lbl_hex.setText("报文: " + frame.hex(" ").upper())
        except Exception:
            pass

    # ====== 界面操作回调 ======
    def set_lamp(self, val):
        if self.hazard_on:
            self.show_toast("双闪开启中，请先关闭双闪")
            return
        self.trigger_jump(lamp_val=val)
        
    def toggle_hazard(self):
        self.hazard_on = not self.hazard_on
        self.btn_hazard.setStyleSheet("background-color: #409eff; color: white;" if self.hazard_on else "")

    def horn_press(self):
        if self.hazard_on:
            self.show_toast("双闪开启中，请先关闭双闪")
            return
        self.horn_on = True
        self.btn_horn.setStyleSheet("background-color: #409eff; color: white;")

    def horn_release(self):
        self.horn_on = False
        self.btn_horn.setStyleSheet("")

    def change_steer(self, delta, is_center=False):
        if is_center:
            self.steer_angle = 0.0
        else:
            self.steer_angle = max(-500.0, min(500.0, self.steer_angle + delta))
        self.lbl_steer.setText(f"当前: {self.steer_angle:.1f}°")

    def change_speed(self, delta):
        if self.current_gear not in ['D', 'R']:
            return
        self.target_speed = max(6, min(25, self.target_speed + delta))
        self.lbl_target_spd.setText(f"目标车速: {self.target_speed} km/h")

    def change_brake(self, delta):
        self.brake = max(0, min(100, self.brake + delta))
        self.lbl_brake.setText(f"制动踏板: {self.brake} %")

    def set_gear(self, gear):
        # 安全锁
        if self.real_actual_speed != '--':
            if float(self.real_actual_speed) > 0.1:
                self.show_toast(f"换挡失败：当前车速 {self.real_actual_speed}km/h，请踩刹车至 0！")
                return
                
        self.current_gear = gear
        gear_val = {'R': 1, 'N': 2, 'D': 3, 'P': 4}[gear]
        self.trigger_jump(gear_val=gear_val)
        self.update_gear_ui()

    def update_gear_ui(self):
        # 恢复按钮样式
        for b in (self.btn_p, self.btn_r, self.btn_n, self.btn_d):
            b.setStyleSheet("")
            
        # 高亮当前档位
        btn = {'P': self.btn_p, 'R': self.btn_r, 'N': self.btn_n, 'D': self.btn_d}[self.current_gear]
        btn.setStyleSheet("background-color: #409eff; color: white; font-weight: bold;")
        
        # 控制加减速按钮
        is_drive = self.current_gear in ['D', 'R']
        self.btn_spd_up.setEnabled(is_drive)
        self.btn_spd_down.setEnabled(is_drive)

    def reset_all(self):
        self.target_speed = 6
        self.brake = 0
        self.steer_angle = 0.0
        self.hazard_on = False
        self.horn_on = False
        
        self.lbl_target_spd.setText("目标车速: 6 km/h")
        self.lbl_brake.setText("制动踏板: 0 %")
        self.lbl_steer.setText("当前: 0.0°")
        self.btn_hazard.setStyleSheet("")
        self.btn_horn.setStyleSheet("")
        
        self.set_gear('P')

    # ====== 接收实车车速 ======
    def setup_receiver(self):
        def recv_thread():
            sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock_recv.bind(('0.0.0.0', self.PORT))
            except Exception:
                return

            while self.is_running:
                try:
                    data, _ = sock_recv.recvfrom(2048)
                    if len(data) == 13 and data[0] == 0x08:
                        if data[1:5] == b'\x00\x00\x05\x02':
                            speed_kmh = data[6]
                            self.real_actual_speed = float(speed_kmh)
                            # 跨线程更新 UI 用 QTimer.singleShot
                            QTimer.singleShot(0, self.update_actual_speed_ui)
                except Exception:
                    pass

        self.recv_thread = threading.Thread(target=recv_thread, daemon=True)
        self.recv_thread.start()

    def update_actual_speed_ui(self):
        if self.real_actual_speed == '--':
            self.lbl_actual_speed.setText("实际车速: -- km/h")
        else:
            self.lbl_actual_speed.setText(f"实际车速: {self.real_actual_speed:.1f} km/h")

    def closeEvent(self, event):
        self.is_running = False
        self.send_timer.stop()
        self.sock.close()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = CANControllerGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()