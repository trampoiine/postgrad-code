import webview
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
class Api:
    """前端 JS 调用 Python 的桥接口子。"""
    def on_action(self, action, payload):
        if action == 'gear':
            print(f'[模拟] 切换档位 -> {payload}')
        elif action == 'accel':
            if payload == 'forward':
                print('[模拟] 前进加速指令已发送')
            else:
                print('[模拟] 倒车加速指令已发送')
        elif action == 'decel':
            if payload == 'forward':
                print('[模拟] 前进减速指令已发送')
            else:
                print('[模拟] 倒车减速指令已发送')
        elif action == 'light':
            print(f'[模拟] 灯光 -> {payload}')


if __name__ == '__main__':
    api = Api()
    
    # 找到 index.html 的绝对路径
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')

    # 核心改变：直接读取 HTML 的内容，而不是交给 pywebview 自己去找
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    window = webview.create_window(
        title='自动驾驶线控系统-制作人:张烔赫、高文豪',
        html=html_content,     # <--- 直接传入 HTML 字符串，不再用 url 参数
        js_api=api,
        width=1000,
        height=560,
        resizable=True,
    )
    
    webview.start(http_port=0)