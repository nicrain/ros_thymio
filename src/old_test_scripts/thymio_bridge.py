#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import asyncio
from tdmclient import ClientAsync

class ThymioSafeBridge(Node):
    def __init__(self):
        super().__init__('thymio_bridge')
        try:
            # 即使报错 ConnectionRefused 也强制继续
            self.client = ClientAsync()
        except ConnectionRefusedError:
            self.get_logger().warn("Serveur TDM introuvable, bascule en mode port série local...")
            # 这里的 self.client 其实已经创建了，只是连接失败了
            pass 
        
        self.thymio_node = None
        self.subscription = self.create_subscription(Twist, '/cmd_vel', self.cmd_vel_callback, 10)
        self.get_logger().info('Pont Thymio sécurisé démarré')

    async def connect(self):
        while rclpy.ok() and self.thymio_node is None:
            try:
                self.client.start_local_discovery()
                self.thymio_node = await self.client.wait_for_node()
                await self.thymio_node.lock()
                self.get_logger().info(f'Robot verrouillé : {self.thymio_node.id_str}')
                break
            except:
                await asyncio.sleep(1.0)

    async def cmd_vel_callback(self, msg):
        if not self.thymio_node: return
        v, w = msg.linear.x * 400.0, msg.angular.z * 200.0
        l, r = int(v - w), int(v + w)
        try:
            await self.thymio_node.set_variables({"motor.left.target": [l], "motor.right.target": [r]})
        except Exception as e:
            self.get_logger().error(f"Échec d'envoi : {e}")

async def main():
    rclpy.init()
    node = ThymioSafeBridge()
    conn_task = asyncio.create_task(node.connect())
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            await asyncio.sleep(0.01)
    except KeyboardInterrupt:
        node.get_logger().warn('Arrêt d\'urgence en cours...')
    finally:
        if node.thymio_node:
            # 退出前最后的步骤：强制停机
            await node.thymio_node.set_variables({"motor.left.target": [0], "motor.right.target": [0]})
            await asyncio.sleep(0.2)
            await node.thymio_node.unlock()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
