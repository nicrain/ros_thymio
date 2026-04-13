import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, Twist

class GazeLogic(Node):
    def __init__(self):
        super().__init__('gaze_logic')
        self.subscription = self.create_subscription(Point, '/gaze_data', self.callback, 10)
        self.publisher_ = self.create_publisher(Twist, '/cmd_vel', 10)

    def callback(self, msg):
        twist = Twist()
        # 逻辑：x < 0.3 左转，x > 0.7 右转，中间直行
        if msg.x == 0.0 and msg.y == 0.0: 
            twist.linear.x = 0.0
            twist.angular.z = 0.0
            self.get_logger().info("Signal perdu, arrêt du mouvement")
        else:
            # 原有的控制逻辑...
            if msg.x < 0.3:
                twist.linear.x = 0.05
                twist.angular.z = 0.8
            elif msg.x > 0.7:
                twist.linear.x = 0.05
                twist.angular.z = -0.8
            else:
                twist.linear.x = 0.1
                twist.angular.z = 0.0

        self.publisher_.publish(twist)

def main():
    rclpy.init()
    rclpy.spin(GazeLogic())
    rclpy.shutdown()

if __name__ == '__main__':
    main()
