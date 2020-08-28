#!/usr/bin/python

import socket
import math
import time
import Vectors
import struct
import threading
import Queue
import rospy
from std_msgs.msg import String
import sys

# local collection of library functions (refactored)
import locallib

from ar_track_alvar_msgs.msg import AlvarMarkers
from gazebo_msgs.srv import GetModelState
#import tf

# for Euler
import tf.transformations
from tf.transformations import *

from trac_ik_python.trac_ik import IK

#import random

import tf2_ros
import tf2_geometry_msgs

import geometry_msgs.msg

# refer to http://sdk.rethinkrobotics.com/wiki/IK_Service_Example

from geometry_msgs.msg import (
        PoseStamped,
        Pose,
        Point,
        Quaternion,
        )
from std_msgs.msg import Header

#from baxter_core_msgs.srv import (
#        SolvePositionIK,
#        SolvePositionIKRequest,
#        )
#import baxter_interface
#import baxter_external_devices
# from baxter_interface import CHECK_VERSION

### Needed?
#mutex = threading.Lock()

# TO DO: use laser rangefinder to improve z co-ordinate of block

def this_marker(marker):
    # TO DO: handle markers other than the current known-top marker
    #result = (marker.header.frame_id != 'head_camera') and (locallib.block_nr(marker) == 1)
    result = (marker.header.frame_id != 'head_camera') and (marker.id == 5)
    return result

locallib.init(nodename='pickup_alvar_demo',target_marker_fn=this_marker)

#global tf_buffer
#tf_buffer = locallib.tf_buffer

global target_cube
target_cube = 1
global target_object
target_object = 'marker'+str(target_cube)
global target_marker_id
target_marker_id = 5

#######################################################################################
# Optional: for testing: do we have Baxter or Rosie? (only available during simulation)
#######################################################################################

from gazebo_msgs.srv import GetWorldProperties
parent_frame='head'
try:
    get_world_properties = rospy.ServiceProxy('/gazebo/get_world_properties', GetWorldProperties)
    props = get_world_properties()
    for name in props.model_names:
      if name=='mobility_base' or name=='baxter':
        parent_model = name + "::head"
except rospy.ServiceException as e:
    print e
    sys.exit(1)

##
## This data is only available from simulation
##

from gazebo_msgs.srv import GetModelState
model_coordinates = rospy.ServiceProxy('/gazebo/get_model_state', GetModelState)
print 'get position of marker wrt ',parent_model
coords = model_coordinates(target_object, parent_model)
blockpose = coords.pose
if coords.success:
  print('block pose',blockpose,'relative to',parent_model)
else:
  print('could not get marker1 position wrt',parent_model)

truepos = blockpose.position
tori = blockpose.orientation
# There are several different ROS implementations of ``quaternion'' depending on library/fn
# Here we use tf.transformations.euler_from_quaternion which requires a vector (x,y,y,w)
# (https://answers.ros.org/question/69754/quaternion-transformations-in-python/)
tquat = (tori.x,tori.y,tori.z,tori.w)
(trueroll,truepitch,trueyaw) = tf.transformations.euler_from_quaternion(tquat)
print 'true RPW',trueroll,truepitch,trueyaw

global mylimb
mylimb = 'left'
global otherlimb
otherlimb = 'right'

print 'init / open gripper'
gripper = locallib.init_gripper(mylimb)
gripper.open()
rospy.sleep(1)
print 'gripper open'

global avgpos
global avgyaw
global last_seen 
avgpos = None
avgyaw = None
last_seen = None

#def getavgpos():
#    global avgpos
#    global avgyaw
#    print 'awaiting marker update'
#    rospy.sleep(2)
#    result = locallib.getavgpos(target_marker_id)
#    if result != None:
#        (avgpos,avgyaw) = locallib.getavgpos(target_marker_id)
#        print 'marker update:',(avgpos,avgyaw)

def getavgpos(left_only=False):
    global avgpos
    global avgyaw
    global last_seen
    avgmarkerpos = locallib.avgmarkerpos
    d0 = {}
    d = {}
    print 'awaiting Alvar avg'
    rospy.sleep(3)
    if target_marker_id in avgmarkerpos:
        d0 = avgmarkerpos[target_marker_id]
    if 'right_hand_camera' and not left_only in d0:
        d = d0['right_hand_camera']
    if 'left_hand_camera' in d0:
        d = d0['left_hand_camera']
    if 'avg' in d:
        avgpos = d['avg']
        avgyaw = d['avg_rpy'][2]
        last_seen = d['last_seen']
    print '- alvar','avg pos',avgpos,'avg yaw',avgyaw,'last sighting',rospy.get_time() - last_seen,'s ago'

def getavgpos_any():
    getavgpos(left_only=False)

def getavgpos_left():
    getavgpos(left_only=True)


# FIXME: back off and try from more positions
# FIXME: point right camera at best guess position
# FIXME: give up if the marker is consistently not found

otherpose = locallib.get_frame(otherlimb+'_gripper','base')
print 'camera on',otherlimb,'...'
locallib.solve_move_trac(otherlimb, locallib.make_pose_stamped_rpy(otherpose.transform.translation, frame_id='base', r=3.3, p=0.0))

#print '******* move to basic sighting pos ********'
#print 'look for cube from pos1'
#locallib.solve_move_trac(mylimb, locallib.make_pose_stamped(Point(x=0.49, y=-0.02, z=0.0), frame_id='base'))
#getavgpos_any()
#print 'look for cube from pos2'
#locallib.solve_move_trac(mylimb, locallib.make_pose_stamped(Point(x=0.49, y= 0.02, z=0.0), frame_id='base'))
#getavgpos_any()
#last_seen_sighting = last_seen
#print "Last seen:", last_seen - last_seen_sighting, "since last sighting", "seen?", last_seen > last_seen_sighting
#last_seen_sighting = last_seen

grab = False
stage = 0

while not grab:
    print 'stage',stage
    if stage == 0:
        # No sighting available
        locallib.solve_move_trac(mylimb, locallib.make_pose_stamped(Point(x=0.49, y=-0.02, z=0.2), frame_id='base'))
        last_seen = 0
        last_seen_sighting = 0
    if stage == 1:
        # Use whatever average position we have as a basis for first proper sighting
        print '******* move to sighting pos ********'
        locallib.solve_move_trac(mylimb, locallib.make_pose_stamped_yaw(Point(x=avgpos.x+0.1, y=avgpos.y, z=avgpos.z+0.20), frame_id='head', yaw=avgyaw))
    if stage == 2:
        print '********* move to pregrab **********'
        locallib.solve_move_trac(mylimb, locallib.make_pose_stamped_yaw(Point(x=avgpos.x, y=avgpos.y, z=avgpos.z+0.12), frame_id='head', yaw=avgyaw))
    if stage == 3:
        print '********* move to grab **********'
        locallib.solve_move_trac(mylimb, locallib.make_pose_stamped_yaw(Point(x=avgpos.x, y=avgpos.y, z=avgpos.z+0.05), frame_id='head', yaw=avgyaw))
        grab = True
    # update vision QOS info
    getavgpos_left()
    vision_valid = last_seen > last_seen_sighting
    print "Last seen:", last_seen - last_seen_sighting, "since last sighting"
    print "Vision valid?", vision_valid
    last_seen_sighting = last_seen
    # if still have vision, proceed, otherwise back up
    if vision_valid:
        stage = stage + 1
    else:
        stage = 1

###
### Close grippers
### 

print 'close (grab)'
rospy.sleep(1.0)
gripper.close()
rospy.sleep(1.0)

print 'lift'
locallib.solve_move_trac(mylimb, locallib.make_pose_stamped(Point(x=avgpos.x, y=avgpos.y, z=avgpos.z+0.20), frame_id='head'))

print 'get new position of marker'

coords = model_coordinates(target_object, parent_model)
if coords.success:
  print('block original position',truepos,'relative to',parent_model)
  pose = coords.pose
  newpos = pose.position
  print('block current position',newpos)
  # should be 15cm higher
  # note: more properly we would expect the cube to be approx 5cm below the 'frame' (camera) position
  if (abs(newpos.x - truepos.x) < 0.04 and abs(newpos.y - truepos.y) < 0.04 and abs((newpos.z - truepos.z) - 0.14) < 0.04):
    print 'success'
    sys.exit(0)
  else:
    print 'failure, block is at',newpos,'vs originally at',truepos
else:
  print('could not get ',target_object,' position wrt',parent_model)

print 'failure'
sys.exit(1)
