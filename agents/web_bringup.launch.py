#!/usr/bin/env python3
"""JetRover 网页工作台所需的最小 ROS 2 bringup。

保留底盘/舵机、IMU/里程计、深度相机、雷达、rosbridge 和视频流；不启动
厂商演示应用（巡线、目标追踪、AR、手势、雷达玩法）、摇杆控制和 init_pose。
机械臂初始姿态由 snack_butler 的安全状态机负责，网页驾驶统一经过 nav_safety。
"""
import os

from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def launch_setup(_context):
    compiled = os.environ.get('need_compile') == 'True'
    if compiled:
        from ament_index_python.packages import get_package_share_directory
        controller_path = get_package_share_directory('controller')
        peripherals_path = get_package_share_directory('peripherals')
    else:
        controller_path = '/home/ubuntu/ros2_ws/src/driver/controller'
        peripherals_path = '/home/ubuntu/ros2_ws/src/peripherals'

    include = lambda path, arguments=None: IncludeLaunchDescription(
        PythonLaunchDescriptionSource(path), launch_arguments=(arguments or {}).items())
    return [
        Node(package='bringup', executable='startup_check', output='screen'),
        include(os.path.join(controller_path, 'launch/controller.launch.py')),
        # 抓取与深度流都是 16:9 的 640×360；原先 RGB 以 1080p 采集后又在
        # snack_butler 中缩到 640，徒增 USB/DDS/JPEG/CPU 负担与显示延迟。
        # 直接从相机输出 640×360，保留 30fps 和原始几何比例。
        include(os.path.join(peripherals_path, 'launch/depth_camera.launch.py'), {
            'color_width': '640', 'color_height': '360', 'color_fps': '30',
        }),
        include(os.path.join(peripherals_path, 'launch/lidar.launch.py')),
        ExecuteProcess(
            cmd=['ros2', 'launch', 'rosbridge_server', 'rosbridge_websocket_launch.xml'],
            output='screen'),
        Node(package='web_video_server', executable='web_video_server', output='screen'),
    ]


def generate_launch_description():
    return LaunchDescription([OpaqueFunction(function=launch_setup)])
