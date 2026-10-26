"""通用 8 字节数据模型，不包含待完成控制功能的实现。"""


class CANDataModel:
    """D2、D3 留给方向盘，D5 为功能指令，其余字节保持为零。"""

    def __init__(self):
        self.data = [0x00] * 8

    def set_byte(self, index, value):
        """设置一个字节；越界值明确报错，避免静默回绕。"""
        if not isinstance(index, int) or not 0 <= index < 8:
            raise ValueError("字节索引必须为 0～7 的整数")
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("字节值必须为 0～255 的整数")
        self.data[index] = value

    def get_byte(self, index):
        if not isinstance(index, int) or not 0 <= index < 8:
            raise ValueError("字节索引必须为 0～7 的整数")
        return self.data[index]

    def get_data(self):
        """返回副本，避免调用方意外修改内部状态。"""
        return self.data.copy()