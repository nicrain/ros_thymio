import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, Twist
import time

class GazeLogicSafe(Node):
    def __init__(self):
        super().__init__('gaze_logic')
        self.publisher_ = self.create_publisher(Twist, '/cmd_vel', 10)
        self.subscription = self.create_subscription(Point, '/gaze_data', self.callback, 10)
        self.last_msg_time = time.time()
        # 定时器：每 0.1 秒检查一次数据是否过期
        self.create_timer(0.1, self.watchdog_check)

    def callback(self, msg):
        self.last_msg_time = time.time() # 刷新时间戳
        twist = Twist()
        # 控制逻辑
        if msg.x < 0.3: twist.angular.z = 0.8; twist.linear.x = 0.05
        elif msg.x > 0.7: twist.angular.z = -0.8; twist.linear.x = 0.05
        else: twist.linear.x = 0.1
        self.publisher_.publish(twist)

    def watchdog_check(self):
        # 如果超过 0.5 秒没收到眼神数据，判定为失控，发送停止指令
        if time.time() - self.last_msg_time > 0.5:
            stop_msg = Twist()
            self.publisher_.publish(stop_msg)
            # self.get_logger().warn("⚠️ 眼神信号丢失，自动刹车")

def main():
    rclpy.init(); rclpy.spin(GazeLogicSafe()); rclpy.shutdown()

if __name__ == '__main__':
    main()
