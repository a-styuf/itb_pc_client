# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QMainWindow, QTableWidgetItem

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt
import numpy as np
import copy


class Layout(QVBoxLayout):
    def __init__(self, root):
        super().__init__()
        self.figure = plt.figure()
        self.canvas = FigureCanvas(self.figure)
        # self.toolbar = NavigationToolbar(self.canvas, root)
        # self.addWidget(self.toolbar)
        self.addWidget(self.canvas)

    def plot_channel_current(self, channel_graph_data):  # graph_data в формате [["Имя1, ед.изм.", [data]], ["Имя2, ед.изм.", [data]]...]
        """

        :param channel_graph_data: данные в формате [[["Время_1, с",data_list], ["Ток_1, А", data_list]],
                                                    [["Время_2, с",data_list], ["Ток_2, А", data_list]],
                                                    ...
                                                    [["Время_N, с",data_list], ["Ток_N, А", data_list]]]
        :return:
        """
        current_min = 1E-12
        current_max = 1E+05
        # проверка на необходимость перерисовки
        try:
            # очистим график
            self.figure.clear()
            # создадим оси
            axes = self.figure.add_subplot(111)
            # data prepare
            times_label = [var[0][0] for var in channel_graph_data]
            times_list = [var[0][1] for var in channel_graph_data]
            currents_label = [var[1][0] for var in channel_graph_data]
            currents_list = [var[1][1] for var in channel_graph_data]
            currents_pos_list = copy.deepcopy(currents_list)
            currents_neg_list = copy.deepcopy(currents_list)
            for j, currents in enumerate(currents_list):
                for i, current in enumerate(currents):
                    if current <= -current_min:
                        currents_neg_list[j][i] = -current
                    elif current >= current_min:
                        currents_pos_list[j][i] = current
                    else:
                        currents_pos_list[j][i] = current_min
                        currents_neg_list[j][i] = current_min
            for num, time in enumerate(times_list):
                axes.plot(time, currents_pos_list[num], line_type_from_index(2*num + 0), label=currents_label[num] + " +")
                axes.plot(time, currents_neg_list[num], line_type_from_index(2*num + 1), label=currents_label[num] + " -")
            #
            axes.set_title("Зависимость тока ИТБ от времени")
            axes.set_xlabel("Время, с")
            axes.set_ylim(bottom=current_min)
            axes.set_yscale("log")
            axes.legend(loc=2)
            axes.grid()
            # refresh canvas
            self.canvas.draw()
        except Exception as error:
            print("plot_channel_current: " + str(error))
        pass

    def plot_osc_dnt(self, graph_data, osc_data_type=0):
        try:
            # отрисуем график
            self.figure.clear()
            # create an axis
            axes = self.figure.add_subplot(111)
            # plot data
            time = graph_data[0][1]
            read_flag = 0
            for num, var in enumerate(graph_data[1:]):
                if var[1]:
                    read_flag = 1
                    axes.plot(time, var[1], line_type_from_index(num), label=var[0])
            if read_flag:
                axes.set_title("Осциллограмма ДНТ")
                axes.set_xlabel("Время, с")
                axes.legend(loc=0)
                axes.grid()
                # refresh canvas
                self.canvas.draw()
        except Exception as error:
            print(error)


def line_type_from_index(n):
    color_line = ["r", "b", "g", "c", "m", "y", "k"]
    style_line = ["-", "--", "-.", ":"]
    try:
        color = color_line[n % len(color_line)]
        style = style_line[n // len(color_line)]
        return style + color
    except IndexError:
        return "-r"
