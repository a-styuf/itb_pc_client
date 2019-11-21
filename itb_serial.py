import serial
import serial.tools.list_ports
import threading
import time
import crc16
import copy


class ITBSerial(serial.Serial):
    def __init__(self, **kw):
        serial.Serial.__init__(self)
        self.serial_numbers = []  # это лист возможных серийников!!! (не строка)
        self.baudrate = 9600
        self.timeout = 0.03
        self.port = "COM0"
        self.row_data = b""
        self.read_timeout = 0.5
        self.debug = False
        self.crc_check = True
        for key in sorted(kw):
            if key == "serial_numbers":
                self.serial_numbers = kw.pop(key)
            elif key == "baudrate":
                self.baudrate = kw.pop(key)
            elif key == "timeout":
                self.timeout = kw.pop(key)
            elif key == "port":
                self.port = kw.pop(key)
            elif key == "debug":
                self.debug = kw.pop(key)
            elif key == "crc":
                self.crc_check = kw.pop(key)
            else:
                pass
        # общие переменные
        self.s_addr = 0x00  # self address
        self.d_addr = 0x01  # device address
        self.seq_num = 0
        self.com_queue = []  # очередь отправки
        self.nansw = 0  # неответы
        self.answer_data = []
        self.com_rec_flag = 0
        self.read_data = b""
        self.read_flag = 0
        self.state_string = {
            -3: "Связь потеряна",
            -2: "Устройство не отвечает",
            -1: "Не удалось установить связь",
            +0: "Подключите устройство",
            +1: "Связь в норме",
        }
        self.state = 0
        self.log_buffer = []
        # для работы с потоками
        self.read_write_thread = None
        self._close_event = threading.Event()
        self.read_write_thread = threading.Thread(target=self.thread_function, args=(), daemon=True)
        self.read_write_thread.start()
        self.log_lock = threading.Lock()
        self.com_send_lock = threading.Lock()
        self.ans_data_lock = threading.Lock()

    def open_id(self):  # функция для установки связи с КПА
        com_list = serial.tools.list_ports.comports()
        for com in com_list:
            self._print("Find:", str(com), com.serial_number)
            for serial_number in self.serial_numbers:
                self._print("ID comparison:", com.serial_number, serial_number)
                if com.serial_number is not None:
                    if com.serial_number.find(serial_number) >= 0:
                        self._print("Connection to:", com.device)
                        self.port = com.device
                        try:
                            self.open()
                            self._print("Success connection!")
                            self.state = 1
                            self.nansw = 0
                            return True
                        except serial.serialutil.SerialException as error:
                            self._print("Fail connection")
                            self._print(error)
        self.state = -1
        return False

    def _print(self, *args):
        if self.debug:
            print_str = get_time() + " "
            for arg in args:
                print_str += " " + str(arg)
            print(print_str)

    def close_id(self):
        self.close()
        self.state = 0
        pass

    def reconnect(self):
        self.close_id()
        self.open_id()

    def request(self, req_type="mirror", data=None):

        if req_type == "mirror":
            data_to_send = self.data_to_send_form(cmd=0x00, data=data)
        elif req_type == "get_adc":
            data_to_send = self.data_to_send_form(cmd=0x01)
        elif req_type == "measure_mode":
            data_to_send = self.data_to_send_form(cmd=0x02, data=data)
        elif req_type == "get_channel_data":
            data_to_send = self.data_to_send_form(cmd=0x03)
        elif req_type == "dac_set":
            data_to_send = self.data_to_send_form(cmd=0x04, data=data)
        elif req_type == "itb_param_write":
            data_to_send = self.data_to_send_form(cmd=0x05, data=data)
        elif req_type == "itb_param_read":
            data_to_send = self.data_to_send_form(cmd=0x06)
        elif req_type == "dbg_start":
            data_to_send = self.data_to_send_form(cmd=0x07, data=data)
        else:
            data_to_send = self.data_to_send_form(cmd=0x00)
        self._print("Try to send command <%s>:" % req_type, bytes_array_to_str(data_to_send))
        with self.com_send_lock:
            self.com_queue.append(data_to_send)
        pass

    def data_to_send_form(self, cmd_type=0x00, cmd=0x01, data=None):  # data to send form
        if data:
            data_len = len(data) if len(data) < 256 else 255
        else:
            data_len = 0
        data_to_send = [self.d_addr, self.s_addr, self.seq_num & 0xFF, cmd_type, cmd, data_len]
        if data_len > 0:
            data_to_send.extend(data[0:data_len])
        com_crc16 = crc16.calc_to_list(data_to_send, len(data_to_send))
        data_to_send.extend(com_crc16)
        self.seq_num += 1
        return data_to_send

    def thread_function(self):
        try:
            while True:
                nansw = 0
                if self.is_open is True:
                    time.sleep(0.010)
                    # отправка команд
                    if self.com_queue:
                        with self.com_send_lock:
                            data_to_send = self.com_queue.pop(0)
                            comm = data_to_send[4]
                        if self.in_waiting:
                            print("In input buffer %d bytes" % self.in_waiting)
                            self.read(self.in_waiting)
                        try:
                            self.read(self.in_waiting)
                            self.write(bytes(data_to_send))
                            nansw = 1
                            self._print("Send packet: ", bytes_array_to_str(data_to_send))
                        except serial.serialutil.SerialException as error:
                            self.state = -3
                            self._print("Send error: ", error)
                            pass
                        with self.log_lock:
                            self.log_buffer.append(get_time() + bytes_array_to_str(bytes(data_to_send)))
                        # прием ответа: ждем ответа timeout ms
                        buf = bytearray(b"")
                        read_data = bytearray(b"")
                        time_start = time.perf_counter()
                        while True:
                            time.sleep(0.01)
                            timeout = time.perf_counter() - time_start
                            if timeout >= self.read_timeout:
                                break
                            try:
                                read_data = self.read(128)
                                self.read_data = read_data
                            except (TypeError, serial.serialutil.SerialException, AttributeError) as error:
                                self.state = -3
                                self._print("Receive error: ", error)
                                pass
                            if read_data:
                                self._print("Receive data with timeout <%.3f>: " % self.timeout, bytes_array_to_str(read_data))
                                with self.log_lock:
                                    self.log_buffer.append(get_time() + bytes_array_to_str(read_data))
                                read_data = buf + bytes(read_data)  # прибавляем к новому куску старый кусок
                                self._print("Data to process: ", bytes_array_to_str(read_data))
                                if len(read_data) >= 8:
                                    if read_data[0] == 0x00:
                                        if len(read_data) >= read_data[5] + 8:  # проверка на запрос
                                            self._print("CRC16 check (0 is valid): ",
                                                        hex(crc16.modbus_crc16(read_data[:read_data[5] + 8])))
                                            if crc16.modbus_crc16(read_data[:read_data[5] + 8]) == 0 or self.crc_check is False:
                                                if comm == read_data[4]:
                                                    nansw -= 1
                                                    self.state = 1
                                                    with self.ans_data_lock:
                                                        self.answer_data.append([read_data[4], read_data[6:6+read_data[5]]])
                                                        self._print("Command <0x%02X> was read: " % read_data[4],
                                                                    bytes_array_to_str(read_data[6:6+read_data[5]]))
                                                    break
                                                else:
                                                    self._print("Answer error")
                                                    self.state = -3
                                        else:
                                            buf = read_data
                                            read_data = bytearray(b"")
                                    else:
                                        buf = read_data[1:]
                                        read_data = bytearray(b"")
                                else:
                                    buf = read_data
                                    read_data = bytearray(b"")
                                pass
                            else:
                                pass
                else:
                    pass
                if nansw == 1:
                    self.state = -3
                    self.nansw += 1
                    self._print("Timeout error")
                if self._close_event.is_set() is True:
                    self._close_event.clear()
                    return
        except Exception as error:
            self._print(error)
        pass

    def get_log(self):
        with self.log_lock:
            log = copy.deepcopy(self.log_buffer)
            self.log_buffer = []
        return log


def get_time():
    return time.strftime("%H-%M-%S", time.localtime()) + "." + ("%.3f:" % time.perf_counter()).split(".")[1]


def str_to_list(send_str):  # функция, которая из последовательности шестнадцетиричных слов в строке без
    send_list = []  # идентификатора 0x делает лист шестнадцетиричных чисел
    send_str = send_str.split(' ')
    for i, ch in enumerate(send_str):
        send_str[i] = ch
        send_list.append(int(send_str[i], 16))
    return send_list


def bytes_array_to_str(bytes_array):
    bytes_string = ""
    for num, ch in enumerate(bytes_array):
        byte_str = "" if num % 2 else " "
        byte_str += ("%02X" % bytes_array[num])
        bytes_string += byte_str
    return bytes_string


if __name__ == "__main__":
    itb_serial = ITBSerial(serial_numbers=["207733835048"], debug=True)
    itb_serial.open_id()
    # Проверка коанды зеркала
    itb_serial.request(req_type="mirror", data=[0, 1, 2, 3, 4])
    time.sleep(0.1)
    # Проверка коанды set_channel_gpio
    # itb_serial.request(req_type="set_channel_gpio", data=[0, 0, 1])
    # time.sleep(0.5)
    # itb_serial.request(req_type="set_channel_gpio", data=[0, 0, 0])
    # time.sleep(0.5)
    # itb_serial.request(req_type="set_channel_gpio", data=[0, 0, 1])
    # time.sleep(0.5)
    # itb_serial.request(req_type="set_channel_gpio", data=[0, 0, 0])
    # time.sleep(0.5)
    pass
