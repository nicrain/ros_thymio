import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point
import socket
import json

class TobiiReceiver(Node):
    def __init__(self):
        super().__init__('tobii_receiver')
        self.publisher_ = self.create_publisher(Point, '/gaze_data', 10)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 5005))
        self.sock.setblocking(False)
        self.create_timer(0.01, self.receive_callback) # 100Hz 频率
        self.get_logger().info("Nœud de réception démarré, publication des données oculaires vers un topic ROS 2...")

    def receive_callback(self):
        try:
            data, addr = self.sock.recvfrom(1024)
            val = json.loads(data.decode())
            msg = Point()
            msg.x, msg.y = float(val['x']), float(val['y'])
            self.publisher_.publish(msg)
        except:
            pass

def main():
    rclpy.init()
    rclpy.spin(TobiiReceiver())
    rclpy.shutdown()

if __name__ == '__main__':
    main()
