#!/usr/bin/env python3
"""只启动在线探索所需的 SLAM Toolbox + Nav2。

机器人基础驱动、雷达、相机、TF 和里程计已经由 start_app_node.service 启动，
这里不能再用厂商顶层 slam.launch.py（会重复启动整套硬件节点）。
"""
import os

from launch import LaunchDescription, LaunchService
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import LoadComposableNodes, Node
from launch_ros.descriptions import ComposableNode


SLAM_ROOT = '/home/ubuntu/ros2_ws/src/slam'
NAV_ROOT = '/home/ubuntu/ros2_ws/src/navigation'
NAV_PARAMS = os.path.join(NAV_ROOT, 'config/nav2_params.yaml')
CONTROLLER_PARAMS = os.path.join(NAV_ROOT, 'config/nav2_controller_dwb.yaml')
SAFE_PARAMS = '/home/ubuntu/exploration_nav_safety.yaml'


def generate_launch_description():
    container = Node(
        name='nav2_container',
        package='rclcpp_components',
        executable='component_container_isolated',
        parameters=[NAV_PARAMS, {'autostart': True}],
        arguments=['--ros-args', '--log-level', 'info'],
        remappings=[('/tf', 'tf'), ('/tf_static', 'tf_static')],
        output='screen')

    slam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(SLAM_ROOT, 'launch/include/slam_base.launch.py')),
        launch_arguments={
            'use_sim_time': 'false', 'map_frame': 'map', 'odom_frame': 'odom',
            'base_frame': 'base_footprint', 'scan_topic': 'scan', 'enable_save': 'true',
        }.items())

    common = [NAV_PARAMS, SAFE_PARAMS]
    remap = [('/tf', 'tf'), ('/tf_static', 'tf_static')]
    lifecycle_nodes = ['controller_server', 'smoother_server', 'planner_server',
                       'behavior_server', 'bt_navigator', 'waypoint_follower',
                       'velocity_smoother']
    navigation = LoadComposableNodes(
        target_container='nav2_container',
        composable_node_descriptions=[
            ComposableNode(package='nav2_controller', plugin='nav2_controller::ControllerServer',
                           name='controller_server', parameters=[CONTROLLER_PARAMS, SAFE_PARAMS],
                           remappings=remap + [('cmd_vel', 'cmd_vel_nav')]),
            ComposableNode(package='nav2_smoother', plugin='nav2_smoother::SmootherServer',
                           name='smoother_server', parameters=common, remappings=remap),
            ComposableNode(package='nav2_planner', plugin='nav2_planner::PlannerServer',
                           name='planner_server', parameters=common, remappings=remap),
            ComposableNode(package='nav2_behaviors', plugin='behavior_server::BehaviorServer',
                           name='behavior_server', parameters=common,
                           remappings=remap + [('cmd_vel', 'nav_cmd_vel')]),
            ComposableNode(package='nav2_bt_navigator', plugin='nav2_bt_navigator::BtNavigator',
                           name='bt_navigator', parameters=common, remappings=remap),
            ComposableNode(package='nav2_waypoint_follower', plugin='nav2_waypoint_follower::WaypointFollower',
                           name='waypoint_follower', parameters=common, remappings=remap),
            # Nav2 的最终输出只能到 /nav_cmd_vel；只有 nav_safety_guard 解锁后才会转到底盘。
            ComposableNode(package='nav2_velocity_smoother', plugin='nav2_velocity_smoother::VelocitySmoother',
                           name='velocity_smoother', parameters=common,
                           remappings=remap + [('cmd_vel', 'cmd_vel_nav'),
                                               ('cmd_vel_smoothed', 'nav_cmd_vel')]),
            ComposableNode(package='nav2_lifecycle_manager',
                           plugin='nav2_lifecycle_manager::LifecycleManager',
                           name='lifecycle_manager_navigation',
                           parameters=[{'use_sim_time': False, 'autostart': True,
                                        'node_names': lifecycle_nodes}]),
        ])

    return LaunchDescription([container, slam, navigation])


if __name__ == '__main__':
    service = LaunchService()
    service.include_launch_description(generate_launch_description())
    service.run()
