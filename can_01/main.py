import webview
import socket
import struct
import threading
import time
import os
from collections import deque
import random

# ============ 通信参数 ============
TARGET_IP = '127.0.0.1'  # 连实车改为 192.168.1.178
TARGET_PORT = 4001
PERIOD = 0.01            # 10ms
RECV_PORT = 4001         

# ============ 全局状态 ============
state = {
    'target_speed': 0,     # 【修改】初始目标车速为 0
    'brake': 0,            
    'steer_angle': 0.0,    
    'gear_jump': 4,        
    'lamp_jump': 0,        
    'hazard': 0,           
    'horn': 0,             
    'mode_jump': 2,        
    'jump_until': 0,       
    'current_gear': 'P',   
    'sending': False,      # 【修改】启动时默认不发送
    'real_actual_speed': '--', 
}
state_lock = threading.Lock()
sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
window_ref = {'w': None}

def create_packet():
    with state_lock:
        s = state.copy()
        
    d0 = 0x1F
    d1 = s['target_speed'] if s['current_gear'] in ['D', 'R'] else 0
    
    raw_steer = int(s['steer_angle'] * 10)
    encoded_steer = raw_steer & 0xFFFF
    d2 = (encoded_steer >> 8) & 0xFF
    d3 = encoded_steer & 0xFF
    
    d4 = s['brake']
    d5 = (s['gear_jump'] & 0x0F) | \
         ((s['lamp_jump'] & 0x03) << 4) | \
         ((s['hazard'] & 0x01) << 6) | \
         ((s['horn'] & 0x01) << 7)
         
    d6 = 0x00
    d7 = s['mode_jump']
    
    data = bytes([d0, d1, d2, d3, d4, d5, d6, d7])
    return struct.pack(">BI8B", 0x08, 0x00000501, *data)

def send_loop():
    frames = deque()
    last_push = 0
    
    # 即使不发送，跳变信号的有效期也正常走
    with state_lock:
        state['jump_until'] = time.time() + 0.1

    while True:
        now = time.time()

        with state_lock:
            if state['jump_until'] and now > state['jump_until']:
                state['gear_jump'] = 0
                state['lamp_jump'] = 0
                state['mode_jump'] = 0
                state['jump_until'] = 0
                
            sending = state['sending']
            
        if sending:
            pkt = create_packet()
            try:
                sock_send.sendto(pkt, (TARGET_IP, TARGET_PORT))
                frames.append(now)
            except Exception:
                pass

        while frames and now - frames[0] > 1.0:
            frames.popleft()

        if now - last_push > 0.1 and window_ref['w']:
            freq = len(frames) if sending else 0
            with state_lock:
                d2 = (int(state['steer_angle']*10) >> 8) & 0xFF
                d3 = int(state['steer_angle']*10) & 0xFF
                d5 = (state['gear_jump'] & 0x0F) | ((state['lamp_jump'] & 0x03) << 4) | ((state['hazard'] & 0x01) << 6) | ((state['horn'] & 0x01) << 7)
                d1 = state['target_speed'] if state['current_gear'] in ['D', 'R'] else 0
                data_list = [0x1F, d1, d2, d3, state['brake'], d5, 0x00, state['mode_jump']]
                actual_spd = state['real_actual_speed']
                sending_status = state['sending']
                
            full_hex = '08 00 00 05 01 ' + ' '.join(f'{b:02X}' for b in data_list)
            try:
                window_ref['w'].evaluate_js(f'window.updateFreq({freq})')
                window_ref['w'].evaluate_js(f'window.updateData({data_list}, "{full_hex}", "{actual_spd}", {str(sending_status).lower()})')
            except Exception:
                pass
            last_push = now

        time.sleep(PERIOD)

def recv_loop():
    sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock_recv.bind(('0.0.0.0', RECV_PORT))
    except Exception:
        return

    IS_SIMULATION = True 
    
    if IS_SIMULATION:
        while True:
            time.sleep(0.2)
            with state_lock:
                # 如果没发送，模拟车速强制归 0
                if not state['sending']:
                    state['real_actual_speed'] = 0.0
                    continue

                if state['current_gear'] in ['D', 'R'] and state['brake'] == 0:
                    fake_speed = random.uniform(5.0, 8.0) if state['target_speed'] >= 6 else 0.0
                else:
                    fake_speed = 0.0
                state['real_actual_speed'] = round(fake_speed, 1)
        return

    while True:
        try:
            data, addr = sock_recv.recvfrom(2048)
            if len(data) == 13 and data[0] == 0x08:
                if data[1:5] == b'\x00\x00\x05\x02':
                    speed_kmh = data[6] 
                    with state_lock:
                        state['real_actual_speed'] = float(speed_kmh)
        except Exception:
            pass

class Api:
    def on_action(self, action, payload):
        if action == 'speed':
            with state_lock:
                if state['current_gear'] not in ['D', 'R']: return {'speed': state['target_speed']}
                if payload == 'up': state['target_speed'] = min(25, state['target_speed'] + 1)
                elif payload == 'down': state['target_speed'] = max(0, state['target_speed'] - 1) # 【修改】允许减到 0
            return {'speed': state['target_speed']}
            
        elif action == 'brake':
            with state_lock:
                if payload == 'up': state['brake'] = min(100, state['brake'] + 5)
                elif payload == 'down': state['brake'] = max(0, state['brake'] - 5)
            return {'brake': state['brake']}
            
        elif action == 'brake_reset':
            with state_lock:
                state['brake'] = 0
            return {'brake': 0}

        elif action == 'steering':
            with state_lock:
                if payload == 'left': state['steer_angle'] = min(500.0, state['steer_angle'] + 20.0)
                elif payload == 'right': state['steer_angle'] = max(-500.0, state['steer_angle'] - 20.0)
                elif payload == 'center': state['steer_angle'] = 0.0
                val = state['steer_angle']
            return {'steering': val}

        elif action == 'gear':
            with state_lock:
                current_spd = state['real_actual_speed']
                if current_spd != '--' and float(current_spd) > 0.1:
                    return {'ok': False, 'msg': f'换挡失败：当前车速 {current_spd}km/h，请踩刹车至 0！'}
                
                gear_map = {'R': 1, 'N': 2, 'D': 3, 'P': 4}
                if payload in gear_map:
                    state['gear_jump'] = gear_map[payload]
                    state['current_gear'] = payload
                    state['jump_until'] = time.time() + 0.1
            return {'ok': True, 'speed': state['target_speed']}

        elif action == 'lamp':
            with state_lock:
                lamp_map = {'off': 1, 'left': 2, 'right': 3}
                if payload in lamp_map:
                    state['lamp_jump'] = lamp_map[payload]
                    state['jump_until'] = time.time() + 0.1
            return {'ok': True}

        elif action == 'toggle':
            with state_lock:
                if payload == 'hazard':
                    state['hazard'] = 1 - state['hazard']
                    return {'state': state['hazard']}
                elif payload == 'horn_on':
                    state['horn'] = 1
                    return {'state': 1}
                elif payload == 'horn_off':
                    state['horn'] = 0
                    return {'state': 0}
                    
        elif action == 'stop':
            with state_lock:
                state['sending'] = False
            return {'ok': True}

        elif action == 'start':  # 【新增】开始发送接口
            with state_lock:
                state['sending'] = True
            return {'ok': True}

        elif action == 'reset':
            with state_lock:
                state['target_speed'] = 0    # 【修改】复位也归 0
                state['brake'] = 0
                state['steer_angle'] = 0.0
                state['current_gear'] = 'P'
                state['gear_jump'] = 4
                state['lamp_jump'] = 1
                state['hazard'] = 0
                state['horn'] = 0
                state['mode_jump'] = 2
                state['jump_until'] = time.time() + 0.1
                state['sending'] = False     # 【修改】复位后处于不发送状态
            return {'ok': True, 'speed': 0}

        return {'ok': False}

if __name__ == '__main__':
    threading.Thread(target=send_loop, daemon=True).start()
    threading.Thread(target=recv_loop, daemon=True).start()
    
    api = Api()
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
    win = webview.create_window('智能驾舱控制台', url=html_path, js_api=api, width=1000, height=750)
    window_ref['w'] = win
    webview.start(http_port=0)