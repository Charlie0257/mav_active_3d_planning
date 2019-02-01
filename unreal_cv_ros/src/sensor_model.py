#!/usr/bin/env python

# ros
import rospy
from unreal_cv_ros.msg import UeSensorRaw
from unreal_cv_ros.srv import GetCameraParams
from sensor_msgs.msg import PointCloud2, PointField

# Image conversion
import io

# Python
import sys
import math
import numpy as np
from struct import pack, unpack
import time


class SensorModel:

    def __init__(self):
        '''  Initialize ros node and read params '''

        # Read in params
        model_type_in = rospy.get_param('~model_type', 'ground_truth')

        # Setup sensor type
        model_types = {'ground_truth': 'ground_truth'}      # Dictionary of implemented models
        selected = model_types.get(model_type_in, 'NotFound')
        if selected == 'NotFound':
            warning = "Unknown sensor model '" + model_type_in + "'. Implemented models are: " + \
                      "".join(["'" + m + "', " for m in model_types])
            rospy.logfatal(warning[:-2])
        else:
            self.model = selected

        # Initialize camera params from unreal client
        rospy.loginfo("Waiting for unreal_ros_client camera params ...")
        rospy.wait_for_service("get_camera_params")
        get_camera_params = rospy.ServiceProxy('get_camera_params', GetCameraParams)
        resp = get_camera_params()
        self.camera_params = [resp.Width, resp.Height, resp.FocalLength]

        # Initialize node
        self.pub = rospy.Publisher("ue_sensor_out", PointCloud2, queue_size=10)
        self.sub = rospy.Subscriber("ue_sensor_raw", UeSensorRaw, self.callback, queue_size=10)

        rospy.loginfo("Sensor model setup cleanly.")

    def callback(self, ros_data):
        ''' Produce simulated sensor outputs from raw binary data '''
        # Read out images
        img_color = np.load(io.BytesIO(bytearray(ros_data.color_data)))
        img_depth = np.load(io.BytesIO(bytearray(ros_data.depth_data)))

        # Build 3D point cloud from depth
        pointcloud = self.depth_to_3d(img_depth)

        # Sensor processing
        # if self.model == 'ground_truth':

        # Pack RGB image (for ros representation)
        rgb = self.rgb_to_float(img_color)
        data = np.dstack((pointcloud, rgb))

        # Publish pointcloud
        msg = PointCloud2()
        msg.header.stamp = ros_data.header.stamp
        msg.header.frame_id = 'camera'
        msg.width = pointcloud.shape[0]
        msg.height = pointcloud.shape[1]
        msg.fields = [
            PointField('x', 0, PointField.FLOAT32, 1),
            PointField('y', 4, PointField.FLOAT32, 1),
            PointField('z', 8, PointField.FLOAT32, 1),
            PointField('rgb', 12, PointField.FLOAT32, 1)]
        msg.is_bigendian = False
        msg.point_step = 16
        msg.row_step = msg.point_step * msg.width
        msg.is_dense = True
        msg.data = np.float32(data).tostring()
        self.pub.publish(msg)

    def depth_to_3d(self, img_depth):
        ''' Create point cloud from depth image and camera params. Returns a width x height x 3 (XYZ) array '''
        # read camera params and create image mesh
        height = self.camera_params[1]
        width = self.camera_params[0]
        center_x = width/2
        center_y = height/2
        f = self.camera_params[2]
        cols, rows = np.meshgrid(np.linspace(0, width - 1, num=width), np.linspace(0, height - 1, num=height))

        # Process depth image from ray length to camera axis depth
        distance = ((rows - center_y) ** 2 + (cols - center_x) ** 2) ** 0.5
        points_z = img_depth / (1 + (distance / f) ** 2) ** 0.5

        # Create x and y position
        points_x = points_z * (cols - center_x) / f
        points_y = points_z * (rows - center_y) / f

        return np.dstack([points_x, points_y, points_z])

    @staticmethod
    def rgb_to_float(img_color):
        ''' Stack uint8 rgb image into a 2D float image (efficiently) for ros compatibility '''
        r = np.ravel(img_color[:, :, 0]).astype(int)
        g = np.ravel(img_color[:, :, 1]).astype(int)
        b = np.ravel(img_color[:, :, 2]).astype(int)
        color = np.left_shift(r, 16) + np.left_shift(g, 8) + b
        packed = pack('%di' % len(color), *color)
        unpacked = unpack('%df' % len(color), packed)
        return np.array(unpacked).reshape((np.size(img_color, 0), np.size(img_color, 1)))


if __name__ == '__main__':
    rospy.init_node('sensor_model', anonymous=True)
    sm = SensorModel()
    try:
        rospy.spin()
    except KeyboardInterrupt:
        print("Shutting down sensor_model")