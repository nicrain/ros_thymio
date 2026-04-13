#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from tdmclient import ClientAsync
import socket
import json
import asyncio
import time
import os  # 在文件顶部导入 os
from threading import Thread

class ThymioGazeSystem(Node):
    def __init__(self):
        super().__init__('thymio_gaze_system')
        self.thymio_node = None
        self.last_msg_time = time.time()
        
        # 初始化连接
        self.client = ClientAsync(tdm_addr="172.27.96.1", tdm_port=8596)

        # UDP Socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 5005))
        self.sock.setblocking(False)

        # 定时器：每0.1秒接收一次，平衡实时性与缓冲区负载
        self.create_timer(0.1, self.udp_receive_loop) 
        self.create_timer(0.2, self.watchdog_check)

        self.get_logger().info("Système en temps réel : réactivité optimisée et arrêt d'urgence")

    def udp_receive_loop(self):
        latest_data = None
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
                latest_data = data
            except (BlockingIOError, socket.error):
                break

        if latest_data:
            try:
                val = json.loads(latest_data.decode())
                self.process_gaze(float(val['x']), float(val['y']))
            except:
                pass

    def process_gaze(self, x, y):
        self.last_msg_time = time.time()
        twist = Twist()
        
        # 1. 优先级最高：向下看 (y > 0.8) -> 后退
        if y > 0.8:
            twist.linear.x = -0.15  # 负值代表后退
            twist.angular.z = 0.0
            
        # 2. 其次判断左右：x < 0.3 为左转
        elif x < 0.3:
            twist.linear.x = 0.1
            twist.angular.z = 1.2
            
        # 3. x > 0.7 为右转
        elif x > 0.7:
            twist.linear.x = 0.1
            twist.angular.z = -1.2
            
        # 4. 其他情况（看中间或上方）：直行
        else:
            twist.linear.x = 0.2
            twist.angular.z = 0.0

        if self.thymio_node:
            # 使用当前的异步发送方式
            asyncio.run_coroutine_threadsafe(self.send_to_robot(twist), self.loop)

    def watchdog_check(self):
        if time.time() - self.last_msg_time > 0.5:
            if self.thymio_node:
                asyncio.run_coroutine_threadsafe(self.send_to_robot(Twist()), self.loop)

    async def send_to_robot(self, twist):
        v, w = twist.linear.x * 400.0, twist.angular.z * 200.0
        l, r = int(v - w), int(v + w)
        l, r = max(min(l, 500), -500), max(min(r, 500), -500)
        try:
            await self.thymio_node.set_variables({"motor.left.target": [l], "motor.right.target": [r]})
        except:
            pass

    async def connect_robot(self):
        self.get_logger().info('Recherche du Thymio en cours...')
        try:
            self.thymio_node = await self.client.wait_for_node()
            await self.thymio_node.lock()
            self.get_logger().info(f'Robot verrouillé : {self.thymio_node.id_str}')
        except Exception as e:
            self.get_logger().error(f"Échec de la connexion : {e}")

async def run_async_tasks(node):
    await node.connect_robot()
    while rclpy.ok():
        await asyncio.sleep(0.1)


def main():
    rclpy.init()
    node = ThymioGazeSystem()
    
    node.loop = asyncio.new_event_loop()
    def start_background_loop(loop):
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_async_tasks(node))
        except:
            pass

    thread = Thread(target=start_background_loop, args=(node.loop,), daemon=True)
    thread.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\nSignal d'arrêt détecté, fermeture en cours...")
    finally:
        print("Exécution de l'arrêt d'urgence matériel...")
        if node.thymio_node:
            try:
                # 使用临时事件循环发送停止指令
                async def final_stop():
                    # 获取控制权并清除指令
                    await node.thymio_node.lock()
                    await node.thymio_node.set_variables({
                        "motor.left.target": [0], 
                        "motor.right.target": [0]
                    })
                    await asyncio.sleep(0.3)
                    await node.thymio_node.unlock()
                
                stop_loop = asyncio.new_event_loop()
                stop_loop.run_until_complete(final_stop())
                stop_loop.close()
                print("Commande matérielle envoyée.")
            except Exception as e:
                print(f"Échec de l'envoi de la commande d'arrêt : {e}")

        # 清理并退出
        print("Fermeture du programme...")
        try:
            node.destroy_node()
            rclpy.shutdown()
        except:
            pass
        # 最后使用强制退出以终止进程
        os._exit(0)

if __name__ == '__main__':
    main()

if __name__ == '__main__':
    main()