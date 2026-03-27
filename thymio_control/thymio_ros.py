#!/usr/bin/env python3
"""Thymio 机器人一体化启动脚本（复制到 thymio_control 以便新路径使用）。"""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import threading

import rclpy
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Range

# 关键函数与原文件保持一致以兼容旧工作流

def run_cmd(cmd, **kwargs):
    return subprocess.Popen(cmd, shell=False, **kwargs)

def stream_output(proc, buffer, label):
    for line in proc.stdout:
        decoded = line.rstrip('\n')
        buffer.append(decoded)
        print(f"[{label}] {decoded}")

def ros2_topic_has_subscriber(topic):
    try:
        out = subprocess.check_output(['ros2', 'topic', 'info', topic], stderr=subprocess.DEVNULL)
        text = out.decode('utf-8', errors='ignore')
        for line in text.splitlines():
            if line.strip().startswith('Subscription count:'):
                _, val = line.split(':', 1)
                return int(val.strip()) > 0
    except subprocess.CalledProcessError:
        return False
    return False

# 省略其余实现细节，完整版本保留于 thymio_tobii/thymio_ros.py

def main():
    print('thymio_control/thymio_ros.py: compatibility shim; prefer thymio_tobii/thymio_ros.py')

if __name__ == '__main__':
    main()
