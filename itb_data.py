import time
import numpy
import copy
from ctypes import c_int8, c_int16
import threading
import configparser
import os
import itb_serial


class ITBData:
    def __init__(self, **kw):

        # настройки итб
        self.fabrication_number = 0
        self.address = 1
        self.channel_num = 2  # максимум 4
        self.baudrate = 9600
        self.serial_numbers = []
        self.debug = []
        self.crc_check = []
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
            elif key == "channel_num":
                self.channel_num = kw.pop(key)
            else:
                pass
        # интерфейс работы с ITB - virtual com port
        self.serial = itb_serial.ITBSerial(baudrate=self.baudrate, serial_numbers=self.serial_numbers, debug=self.debug,
                                           crc=self.crc_check)
        # заготовка для хранения данных прибора
        self.data_name = ["Время, с", "Напряжение, В", "Потребление, мА", "Температура МК, °С", "U подложки, В"]
        self.data = [0 for i in range(len(self.data_name))]
        self.adc_data = [0 for i in range(16)]
        # заготовка для хранения и отображения параметров работы прибора
        self.param_name = ["Время измерения, с", "Мертове время, мс"]
        self.param_default = [1.0, 100]  # следить за значениями по умолчанию!
        self.param = self.param_default
        # данные для графиков
        self.graph_data_max_len = 1000
        self.graph_data = [[], [], []]
        # каналы
        self.channels = [ITBChannel() for i in range(self.channel_num)]
        #
        self._close_event = threading.Event()
        self.parc_thread = threading.Thread(target=self.parc_data, args=(), daemon=True)
        self.data_lock = threading.Lock()
        # инициализация
        self.parc_thread.start()
        pass

    def save_conf_to_file(self, file_name="itb_default.cfg"):
        home_dir = os.getcwd()
        config = configparser.ConfigParser()
        config = self.get_cfg(config)
        try:
            os.mkdir(home_dir + "\\ITB config")
        except OSError:
            pass
        try:
            configfile = open(file_name, 'w')
            config.write(configfile)
            configfile.close()
        except FileNotFoundError as error:
            print(error)
            pass

    def load_conf_from_file(self, file_name="itb_default.cfg"):
        config = configparser.ConfigParser()
        home_dir = os.getcwd()
        try:
            os.mkdir(home_dir + "\\ITB config")
        except OSError as error:
            print(error)
            pass
        config.read(file_name)
        self.set_cfg(config)
        pass

    def get_cfg(self, config):
        for j in range(self.channel_num):
            for i in range(4):
                config["Channel %d: current calibration KU = %d" % (j, 10**i)] = {"a": "%.3E" % self.channels[j].cal_a[i],
                                                                         "b": "%.3E" % self.channels[j].cal_b[i]}
        config["General parameters"] = {"fabrication number": "%s" % self.fabrication_number,
                                        "address": "%d" % self.address}
        return config

    def set_cfg(self, config):
        try:
            for j in range(self.channel_num):
                for i in range(4):
                    self.channels[j].cal_a[i] = float(config["Channel %d: current calibration KU = %d" % (j, 10**i)]["a"])
                    self.channels[j].cal_b[i] = float(config["Channel %d: current calibration KU = %d" % (j, 10**i)]["b"])
            self.fabrication_number = config["General parameters"]["fabrication number"]
            self.address = int(config["General parameters"]["address"])
        except KeyError as error:
            print(error, "ITB config file not found. Use last value")
        pass

    def cmd_get_adc_data(self):
        self.serial.request(req_type="get_adc")

    def cmd_start_measure(self, mode="stop"):
        if mode in "stop":
            self.serial.request(req_type="measure_mode", data=[0x00])
        elif mode in "single":
            self.serial.request(req_type="measure_mode", data=[0x02])
        elif mode in "cycle":
            self.serial.request(req_type="measure_mode", data=[0x01])

    def cmd_read_chan_data(self):
        self.serial.request(req_type="get_channel_data")

    def cmd_dac_set(self, dac_ch1_V=0.0, dac_ch2_V=0.0):
        dac_ch1_data, dac_ch2_data = int(dac_ch1_V*1000), int(dac_ch2_V*1000)
        self.serial.request(req_type="dac_set", data=[(dac_ch1_data >> 8) & 0xFF,
                                                      (dac_ch1_data >> 0) & 0xFF,
                                                      (dac_ch2_data >> 8) & 0xFF,
                                                      (dac_ch2_data >> 0) & 0xFF])

    def cmd_itb_param_write(self):
        param_list = []
        meas_time_ms = int(self.param[0])*1000
        dead_time_ms = int(self.param[1])
        meas_time_ms_list = [((meas_time_ms >> (8*i)) & 0xFF) for i in range(3, -1, -1)]
        dead_time_ms_list = [((dead_time_ms >> (8*i)) & 0xFF) for i in range(3, -1, -1)]
        param_list.extend(meas_time_ms_list)
        param_list.extend(dead_time_ms_list)
        self.serial.request(req_type="itb_param_write", data=param_list)

    def cmd_itb_param_read(self):
        self.serial.request(req_type="itb_param_read")

    def cmd_dbg_start(self, channel=0, ku=0, zero=0):
        self.serial.request(req_type="dbg_start", data=[channel, ku, zero])

    def parc_data(self):
        while True:
            time.sleep(0.01)
            data = []
            with self.serial.ans_data_lock:
                if self.serial.answer_data:
                    data = copy.deepcopy(self.serial.answer_data)
                    self.serial.answer_data = []
            for var in data:
                if var[0] == 0x01:  # получение данных АЦП
                    for i in range(len(var[1]) // 2):
                        with self.data_lock:
                            self.adc_data[i] = int.from_bytes(var[1][2*i:2*i+2], signed=False, byteorder='big')
                    self.parc_adc_data()
                elif var[0] == 0x03:  # получение данных измерений по каналам
                    self.parc_channel_data(var[1])
                elif var[0] == 0x06:  # получение параметров измерения
                    self.parc_itb_parameters(var[1])
            if self._close_event.is_set() is True:
                self._close_event.clear()
                return
        pass

    def parc_adc_data(self):
        # todo
        pass

    def parc_channel_data(self, ful_data):
        for num, channel in enumerate(self.channels):
            data = ful_data[0+num*8:8+num*8]
            channel.data[0] = time.perf_counter()
            channel.data[1] = channel.cal_a[data[0]]*int.from_bytes(data[2:4], signed=True, byteorder='big') + channel.cal_b[data[0]]
            channel.data[2] = int.from_bytes(data[1:2], signed=True, byteorder='big')  # Temperature
            channel.data[3] = int.from_bytes(data[2:4], signed=True, byteorder='big')
            channel.data[4] = int.from_bytes(data[4:6], signed=True, byteorder='big')
            channel.data[5] = int.from_bytes(data[6:8], signed=True, byteorder='big')
            channel.data[6] = int.from_bytes(data[0:1], signed=False, byteorder='big')  # КУ
            # не забываем сделать данные для графиков
            channel.create_graph_data()

    def parc_itb_parameters(self, data):
        self.param[0] = int.from_bytes(data[0:4], signed=False, byteorder='big') / 1000  # время измерения
        self.param[1] = int.from_bytes(data[4:8], signed=False, byteorder='big')  # мертвое измерения

    def create_graph_data(self):
        # добавляем данные
        for num, var in enumerate(self.graph_data):
            var[1].append(float(self.data[num][0]))
            # ограничивываем длину данных для отрисовки
            while 1:
                if len(var[1]) > self.graph_data_max_len:
                    var[1] = var[1][1:]
                else:
                    break
        pass

    def get_channels_graph_data(self):
        graph_data = []
        for num, channel in enumerate(self.channels):
            ch_gr_data = channel.get_current_graph_data()
            ch_gr_data[1][0] = ("K%d:" % num) + ch_gr_data[1][0]
            graph_data.append(ch_gr_data)
        return graph_data

    def get_channels_redraw_status(self):
        return_val = 0
        for num, channel in enumerate(self.channels):
            if channel.get_redraw_status():
                return_val = 1
            else:
                pass
        return return_val

    def get_log_file_title(self):
        name_str = ";".join(self.data_name) + ";"
        for num, channel in enumerate(self.channels):
            name_str += ";".join([(("К%d: " % num) + name) for name in channel.data_name]) + ";"
        return name_str

    def get_log_file_data(self):
        name_str = ";".join([("%.2g" % var) for var in self.data]) + ";"
        for num, channel in enumerate(self.channels):
            chan_list = [("%.3g" % var) for var in channel.data]
            name_str += ";".join(chan_list) + ";"
        return name_str

    def reset_graph_data(self):
        self.graph_data = [[] for i in range(len(self.data_name))]
        pass

    def reset_channel_graph_data(self):
        for channel in self.channels:
            channel.reset_graph_data()
        pass


class ITBChannel:
    def __init__(self):
        self.cal_a = [1., 1., 1., 1.]
        self.cal_b = [0., 0., 0., 0.]
        self.current = 1E-8
        self.adc_measure = 1E-8
        self.adc_signal = 1E-8
        self.adc_zero = 1E-8
        # заготовка для хранения данных измерительных каналов
        self.data_name = ["Время, с", "I, А", "Т,°С", "Ток,кв.", "Сигнал,кв.", "Ноль,кв.", "КУ"]
        self.data = [0. for i in range(len(self.data_name))]
        # данные графика
        self.graph_data_max_len = 1000
        self.graph_data = [[] for i in range(len(self.data_name))]
        self.graph_need_to_redraw = 0

    def create_graph_data(self):
        # добавляем данные
        self.graph_need_to_redraw = 1
        for num, var in enumerate(self.graph_data):
            var.append(float(self.data[num]))
            # ограничивываем длину данных для отрисовки
            while 1:
                if len(var) > self.graph_data_max_len:
                    var = var[1:]
                else:
                    break
        pass

    def get_current_graph_data(self):
        return [self.data_name[0], self.graph_data[0]], [self.data_name[1], self.graph_data[1]]

    def get_redraw_status(self):
        if self.graph_need_to_redraw:
            self.graph_need_to_redraw = 0
            return 1
        else:
            return 0

    def reset_graph_data(self):
        self.graph_data = [[] for i in range(len(self.data_name))]
        pass


def value_from_bound(val, val_min, val_max):
    return max(val_min, min(val_max, val))


def list_to_str(input_list):
    return_str = " ".join(["%04X " % var for var in input_list])
    return return_str
