
import bpy
import json
import os
from mathutils import Vector

# Clear scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Load pose data
with open('temp_pose.json', 'r') as f:
    pose_data = json.load(f)

if pose_data and len(pose_data) > 0:
    landmarks = pose_data[0]
    
    # Create armature
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    armature = bpy.context.object
    
    # Bone connections (simplified human skeleton)
    connections = [
        (11, 13), (13, 15),  # Right arm
        (12, 14), (14, 16),  # Left arm
        (23, 25), (25, 27),  # Right leg  
        (24, 26), (26, 28),  # Left leg
        (11, 12), (11, 23), (12, 24)  # Body
    ]
    
    scale = 5.0
    for start_idx, end_idx in connections:
        if len(landmarks) > max(start_idx, end_idx):
            start = landmarks[start_idx]
            end = landmarks[end_idx]
            
            bone = armature.data.edit_bones.new(f"Bone_{start_idx}_{end_idx}")
            bone.head = (start['x']*scale, start['z']*scale, start['y']*scale)
            bone.tail = (end['x']*scale, end['z']*scale, end['y']*scale)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Export FBX
    bpy.ops.export_scene.fbx(
        filepath='output\pose_data_skeleton.fbx',
        use_selection=True,
        global_scale=1.0
    )
    print(" FBX export completed")
else:
    print(" No pose data found")

# Cleanup
if os.path.exists('temp_pose.json'):
    os.remove('temp_pose.json')
