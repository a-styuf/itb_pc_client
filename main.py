import sys
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush
import main_win
import time
import configparser
import os
import itb_data
import data_graph


class MainWindow(QtWidgets.QMainWindow, main_win.Ui_MainWindow):
    def __init__(self):
        # Это здесь нужно для доступа к переменным, методам
        # и т.д. в файле main_win.py
        #
        super().__init__()
        self.setupUi(self)  # Это нужно для инициализации нашего дизайна
        self.setWindowIcon(QtGui.QIcon('icon.png'))
        self.setWindowTitle("ИТБ Клиент: ИТБ зав.№ не выбран")
        # класс для управления ДНТ
        self.itb = itb_data.ITBData(debug=True, serial_numbers=["207733835048"], baudrate=9600)
        self.reconnectPButt.clicked.connect(self.itb.serial.reconnect)
        # график для отрисовки показаний
        self.graph_layout = data_graph.Layout(self.dataGView)
        self.dataGView.setLayout(self.graph_layout)
        self.graphResetPButt.clicked.connect(self.reset_graph_data)
        # загузка/сохранение конфигурации ПО
        self.used_cfg_file = ""
        self.load_main_cfg()
        # загузка/сохранение конфигурации ДНТ
        self.configOpenQAction.triggered.connect(self.load_device_cfg)
        self.configSaveQAction.triggered.connect(self.save_device_cfg)
        # запуск измерений
        self.singleMeasPButt.clicked.connect(self.single_measurement)
        self.cycleMeasPButt.clicked.connect(self.cycle_measurement)
        self.stopMeasPButt.clicked.connect(self.stop_measurement)
        # чтение результата измерения
        self.singleReadPButton.clicked.connect(self.single_read)
        self.cycleReadPButton.clicked.connect(self.cycle_read)
        self.cycleReadTimer = QtCore.QTimer()
        self.cycleReadTimer.timeout.connect(self.cycle_body)
        # управление параметрами измерений и ИТБ
        self.dacVoltageSetPButton.clicked.connect(self.dac_set)
        self.measurement_param_tables_init()
        self.writeParametersPButton.clicked.connect(self.itb_param_write)
        self.readParametersPButton.clicked.connect(self.itb_param_read)
        # заполнение таблицы с параметрами
        self.param_table_update_timer = QtCore.QTimer()
        self.param_table_update_timer.singleShot(500, self.measurement_param_tables_refresh)
        # отладка
        self.dbgPButton.clicked.connect(self.dbg_start)
        # обновление gui
        self.channels_data_tables_init()
        self.DataUpdateTimer = QtCore.QTimer()
        self.DataUpdateTimer.timeout.connect(self.update_ui)
        self.DataUpdateTimer.start(1000)
        # логи
        self.itb_log_file = None
        self.log_str = ""
        self.recreate_log_files()
        self.logRestartPButt.clicked.connect(self.recreate_log_files)

    # UI #
    def channels_data_tables_init(self):
        self.channelDataTWidget.setRowCount(self.itb.channel_num)
        self.channelDataTWidget.setColumnCount(len(self.itb.channels[0].data_name))
        self.channelDataTWidget.setHorizontalHeaderLabels(self.itb.channels[0].data_name)
        self.channelDataTWidget.setVerticalHeaderLabels([("К%d" % num) for num in range(self.itb.channel_num)])
        for column in range(self.channelDataTWidget.columnCount()):
            if column == self.channelDataTWidget.columnCount() - 1:
                self.channelDataTWidget.setColumnWidth(column, 10)
            else:
                self.channelDataTWidget.setColumnWidth(column, 80)
        self.channelDataTWidget.setRowHeight(self.channelDataTWidget.rowCount() - 1, 10)

    def reset_graph_data(self):
        self.itb.reset_channel_graph_data()

    def single_measurement(self):
        self.itb.cmd_start_measure(mode="single")
        pass

    def cycle_measurement(self):
        self.itb.cmd_start_measure(mode="cycle")
        pass

    def stop_measurement(self):
        self.itb.cmd_start_measure(mode="stop")
        pass

    def single_read(self):
        self.itb.cmd_read_chan_data()
        pass

    def cycle_read(self):
        if self.cycleReadTimer.isActive():
            self.cycleReadPButton.setStyleSheet("background-color: " + "gainsboro")
            self.cycleReadTimer.stop()
        else:
            self.cycleReadTimer.start(1000)
            self.cycleReadPButton.setStyleSheet("background-color: " + "palegreen")
        pass

    def cycle_body(self):
        self.cycleReadTimer.start(self.cycleReadPeriodSBox.value() * 1000)
        self.itb.cmd_read_chan_data()
        pass

    def update_ui(self):
        try:
            # заоплнение таблицы c данными
            for row, channel in enumerate(self.itb.channels):
                for column in range(len(channel.data_name)):
                    table_item = QtWidgets.QTableWidgetItem("%.4G" % channel.data[column])
                    table_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.channelDataTWidget.setItem(row, column, table_item)
            # отрисовка графика
            if self.itb.get_channels_redraw_status():
                self.graph_layout.plot_channel_current(self.itb.get_channels_graph_data())
            # логи
            log_str_tmp = self.itb.get_log_file_data()
            if self.log_str == log_str_tmp:
                pass
            else:
                self.log_str = log_str_tmp
                self.itb_log_file.write(self.log_str + "\n")
            # отображение состояния подключения
            self.statusLEdit.setText(self.itb.serial.state_string[self.itb.serial.state])
        except Exception as error:
            print("update_ui: " + str(error))

    def dac_set(self):
        dac_ch_1 = self.dac1VoltageSBox.value() / 20.  # делим на 10 из-за усиления сигнала для ЦАП1
        dac_ch_2 = self.dac2VoltageSBox.value()
        self.itb.cmd_dac_set(dac_ch1_V=dac_ch_1, dac_ch2_V=dac_ch_2)
        pass

    def measurement_param_tables_init(self):
        self.itbParametersTWidget.setRowCount(len(self.itb.param_name))
        self.itbParametersTWidget.setVerticalHeaderLabels(self.itb.param_name)
        self.itbParametersTWidget.setColumnCount(1)
        self.itbParametersTWidget.setHorizontalHeaderLabels(["Значение"])
        for column in range(self.itbParametersTWidget.columnCount()):
            self.itbParametersTWidget.setColumnWidth(column, 100)
        self.itbParametersTWidget.setColumnWidth(self.channelDataTWidget.columnCount() - 1, 10)
        self.itbParametersTWidget.setRowHeight(self.channelDataTWidget.rowCount() - 1, 10)

    def measurement_param_tables_refresh(self):
        for row, parameters in enumerate(self.itb.param_name):
            table_item = QtWidgets.QTableWidgetItem("%.3G" % self.itb.param[row])
            table_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.itbParametersTWidget.setItem(row, 0, table_item)

    def itb_param_write(self):
        try:
            self.itb.param[0] = int(self.itbParametersTWidget.item(0, 0).text())
        except (ValueError, TypeError):
            self.itb.param[0] = self.itb.param[0]
        try:
            self.itb.param[1] = int(self.itbParametersTWidget.item(1, 0).text())
        except (ValueError, TypeError):
            self.itb.param[1] = self.itb.param[1]
        # заполнение таблицы с параметрами
        self.param_table_update_timer.singleShot(100, self.measurement_param_tables_refresh)
        # раскрашивание кнопок
        self.writeParametersPButton.setStyleSheet("background-color: " + "palegreen")
        self.readParametersPButton.setStyleSheet("background-color: " + "gainsboro")
        # отправка данных
        self.itb.cmd_itb_param_write()
        pass

    def itb_param_read(self):
        # отправка данных
        self.itb.cmd_itb_param_read()
        # заполнение таблицы с параметрами
        self.param_table_update_timer.singleShot(500, self.measurement_param_tables_refresh)
        # раскрашивание кнопок
        self.writeParametersPButton.setStyleSheet("background-color: " + "gainsboro")
        self.readParametersPButton.setStyleSheet("background-color: " + "palegreen")
        pass

    def dbg_start(self):
        channel = self.chanSBox.value()
        ku = self.kuSBox.value()
        zero = self.zeroSignalSBox.value()
        self.itb.cmd_dbg_start(channel=channel, ku=ku, zero=zero)
        pass
    # Config load/save #

    def load_main_cfg(self):
        file_name = "init.cfg"
        config = configparser.ConfigParser()
        config.read(file_name)
        try:
            self.used_cfg_file = config["Last work parameters"]["last used cfg file"]
            self.load_device_cfg_from_file(file_name=self.used_cfg_file)
        except KeyError:
            pass

    def save_main_cfg(self):
        config = configparser.ConfigParser()
        config["Last work parameters"] = {"last used cfg file": self.used_cfg_file}
        try:
            configfile = open("init.cfg", 'w')
            config.write(configfile)
            configfile.close()
        except FileNotFoundError as error:
            print(error)
            pass
        pass

    def load_device_cfg(self):
        home_dir = os.getcwd()
        try:
            os.mkdir(home_dir + "\\ITB config")
        except OSError as error:
            print(error)
            pass
        file_name = QtWidgets.QFileDialog.getOpenFileName(self,
                                                          "Открыть файл конфигурации",
                                                          home_dir + "\\ITB config",
                                                          r"config(*.cfg);;All Files(*)")[0]
        self.load_device_cfg_from_file(file_name=file_name)
        pass

    def load_device_cfg_from_file(self, file_name):
        self.itb.load_conf_from_file(file_name=file_name)
        self.setWindowTitle("ИТБ Клиент: ИТБ зав.№ %s" % self.itb.fabrication_number + " " + file_name)
        self.used_cfg_file = file_name

    def save_device_cfg(self):
        home_dir = os.getcwd()
        try:
            os.mkdir(home_dir + "\\ITB config")
        except OSError:
            pass
        file_name = QtWidgets.QFileDialog.getSaveFileName(self,
                                                          "Сохранить файл конфигурации",
                                                          home_dir + "\\ITB config",
                                                          r"config(*.cfg);;All Files(*)")[0]
        self.itb.save_conf_to_file(file_name=file_name)
        pass

    # LOGs #
    @staticmethod
    def create_log_file(file=None, prefix="", extension=".csv"):
        dir_name = "Logs"
        sub_dir_name = dir_name + "\\" + time.strftime("%Y_%m_%d", time.localtime()) + " Лог"
        sub_sub_dir_name = sub_dir_name + "\\" + time.strftime("%Y_%m_%d %H-%M-%S ",
                                                               time.localtime()) + "Лог"
        try:
            os.makedirs(sub_sub_dir_name)
        except (OSError, AttributeError) as error:
            print(error)
            pass
        try:
            if file:
                file.close()
        except (OSError, NameError, AttributeError) as error:
            print(error)
            pass
        file_name = sub_sub_dir_name + "\\" + time.strftime("%Y_%m_%d %H-%M-%S ",
                                                            time.localtime()) + prefix + " " + extension
        file = open(file_name, 'a')
        return file

    def recreate_log_files(self):
        self.itb_log_file = self.create_log_file(prefix="ИТБ", extension=".csv")
        # заголовки
        self.itb_log_file.write(self.itb.get_log_file_title() + "\n")
        pass

    @staticmethod
    def close_log_file(file=None):
        if file:
            try:
                file.close()
            except (OSError, NameError, AttributeError) as error:
                print(error)
                pass
        pass

    #
    def closeEvent(self, event):
        self.close_log_file(file=self.itb_log_file)
        self.save_main_cfg()
        self.close()
        pass


if __name__ == '__main__':  # Если мы запускаем файл напрямую, а не импортируем
    # QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    # os.environ["QT_SCALE_FACTOR"] = "1.0"
    #
    app = QtWidgets.QApplication(sys.argv)  # Новый экземпляр QApplication
    window = MainWindow()  # Создаём объект класса ExampleApp
    window.show()  # Показываем окно
    app.exec_()  # и запускаем приложение
