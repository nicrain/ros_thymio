#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import asyncio

# 仅从顶层导入，避免子模块路径错误
from tdmclient import ClientAsync

class ThymioBridge(Node):
    def __init__(self):
        super().__init__('thymio_bridge')
        
        # 1. 极简初始化，不带任何参数，绕过所有版本差异
        try:
            self.client = ClientAsync(tdm_addr="172.27.96.1", tdm_port=8596)
        except Exception as e:
            self.get_logger().error(f"Impossible d'initialiser le Client : {e}")
            return

        self.thymio_node = None
        
        # ROS 2 订阅
        self.subscription = self.create_subscription(
            Twist, '/cmd_vel', self.cmd_vel_callback, 10)
        
        self.get_logger().info('Pont Thymio démarré, préparation de la connexion...')

    async def connect_loop(self):
        """核心连接逻辑"""
        self.get_logger().info('Recherche de robots en cours (veuillez vérifier que usbipd est connecté et que chmod a été exécuté)...')
        
        while rclpy.ok() and self.thymio_node is None:
            try:
                # 显式启动本地扫描（新版 API 推荐做法）
                # 注意：即便这里报错也没关系，有些版本是后台自动开启的
                try:
                    self.client.start_local_discovery()
                except:
                    pass

                # 尝试获取节点
                # wait_for_node() 会在发现第一个节点时返回
                self.thymio_node = await self.client.wait_for_node()
                await self.thymio_node.lock()
                
                self.get_logger().info(f'Robot verrouillé avec succès : {self.thymio_node.id_str}')
                break
            except Exception as e:
                # 持续尝试，直到发现设备
                    await asyncio.sleep(2.0)

    async def cmd_vel_callback(self, msg):
        if self.thymio_node is None:
            return

        # 速度转换：ROS (m/s) -> Thymio (-500 to 500)
        # 0.1 m/s 大约对应 Thymio 的 300-400 单位
        v = msg.linear.x * 400.0  
        w = msg.angular.z * 200.0 
        
        l_speed = int(v - w)
        r_speed = int(v + w)

        # 限制范围
        l_speed = max(min(l_speed, 500), -500)
        r_speed = max(min(r_speed, 500), -500)

        try:
            # 使用最稳健的字典传参
            await self.thymio_node.set_variables({
                "motor.left.target": [l_speed],
                "motor.right.target": [r_speed]
            })
        except Exception as e:
            self.get_logger().warn(f"Échec d'envoi de la commande : {e}")

async def main():
    rclpy.init()
    node = ThymioBridge()
    
    # 启动后台异步连接任务
    conn_task = asyncio.create_task(node.connect_loop())
    
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            await asyncio.sleep(0.01)
    except KeyboardInterrupt:
        node.get_logger().info('Signal d\'arrêt détecté, arrêt du robot en cours...')
    finally:
        # --- 关键停止逻辑 ---
        if node.thymio_node:
            try:
                # 1. 强制发送 0 速度
                await node.thymio_node.set_variables({
                    "motor.left.target": [0],
                    "motor.right.target": [0]
                })
                # 2. 等待一瞬间确保指令发出
                await asyncio.sleep(0.2)
                # 3. 解锁机器人
                await node.thymio_node.unlock()
                node.get_logger().info('Robot arrêté et déverrouillé en toute sécurité.')
            except Exception as e:
                node.get_logger().error(f"Échec du nettoyage : {e}")
        
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
